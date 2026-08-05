import asyncio
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Optional, Union
from uuid import UUID

from loguru import logger
from packaging.version import Version
from remnapy import RemnawaveSDK
from remnapy.exceptions import (
    AuthenticationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from remnapy.models import (
    CreateUserRequestDto,
    DeleteUserAllHwidDeviceRequestDto,
    DeleteUserHwidDeviceRequestDto,
    DropByUserIds,
    DropConnectionsRequestDto,
    GetMetadataResponseDto,
    TargetAllNodes,
    UpdateUserRequestDto,
    UserResponseDto,
)
from remnapy.models.hwid import HwidDeviceDto

from src.application.common import Remnawave
from src.application.common.remnawave import T
from src.application.dto import (
    PlanSnapshotDto,
    PoolNodeDto,
    PoolUsageRowDto,
    RemnaSubscriptionDto,
    SquadInfoDto,
    SubscriptionDto,
    UserDto,
)
from src.core.constants import (
    PANEL_DATE_FORMAT,
    REMNAWAVE_MIN_VERSION,
    SQUAD_USAGE_MAX_PAGES,
    USERS_STREAM_MAX_PAGES,
    USERS_STREAM_PAGE_SIZE,
)
from src.core.enums import SubscriptionStatus
from src.core.utils.converters import days_to_datetime, gb_to_bytes
from src.core.utils.time import datetime_now

# Panel field -> local field, for the pairs whose names do not match. The panel's user
# id is `id` on the wire and `user_remna_id` on the subscription row.
SYNC_FIELD_MAP: Final[dict[str, str]] = {"user_remna_id": "id"}

# Local fields that must never be written from panel data, whatever they are called on
# the other side. `SubscriptionDto.id` is the row's primary key while
# `RemnaSubscriptionDto.id` is the panel's user id: same name, unrelated meaning. They
# only started colliding when panel 3.0.0 replaced the user UUID with a numeric id, and
# copying one onto the other rewrites the PK — which `SubscriptionDao.update` then uses
# in its WHERE, sending the whole sync to an unrelated subscription. The panel id has
# exactly one home on the target and SYNC_FIELD_MAP declares it.
SYNC_PROTECTED_FIELDS: Final[frozenset[str]] = frozenset({"id"})


class RemnawaveImpl(Remnawave):
    def __init__(self, sdk: RemnawaveSDK) -> None:
        self.sdk = sdk

    async def try_connection(self) -> Version:
        for attempt in range(1, 4):
            try:
                metadata = await self.sdk.system.get_metadata()
                break
            except AuthenticationError as e:
                logger.error(f"Authentication failed when connecting to Remnawave panel: '{e}'")
                raise
            except Exception as e:
                if attempt < 3:
                    logger.warning(
                        f"Failed to connect to Remnawave panel (attempt {attempt}/3): '{e}', "
                        f"retrying in 5s..."
                    )
                    await asyncio.sleep(5)
                else:
                    logger.error(f"Failed to connect to Remnawave panel after 3 attempts: '{e}'")
                    raise

        if not isinstance(metadata, GetMetadataResponseDto):
            logger.error(f"Invalid response from Remnawave panel: '{metadata}'")
            raise ValueError(f"Invalid response from Remnawave panel: {metadata}")

        panel_version = Version(metadata.version)
        if panel_version < REMNAWAVE_MIN_VERSION:
            logger.error(
                f"Remnawave panel version '{panel_version}' is not compatible. "
                f"Minimum required version: '{REMNAWAVE_MIN_VERSION}'"
            )
            raise ValueError(
                f"Remnawave panel version '{panel_version}' is not compatible. "
                f"Minimum required version: '{REMNAWAVE_MIN_VERSION}'"
            )

        logger.info(f"Successfully connected to Remnawave panel (version: {panel_version})")
        return panel_version

    async def create_user(
        self,
        user: UserDto,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
    ) -> UserResponseDto:
        request_dto = self._build_create_request(user, plan, subscription)

        try:
            remna_user = await self.sdk.users.create_user(request_dto)
            logger.info(
                f"RemnaUser '{remna_user.username}' created successfully. "
                f"id: '{remna_user.id}', telegram_id: '{remna_user.telegram_id}'"
            )
            return remna_user
        except ConflictError:
            logger.warning(f"RemnaUser '{request_dto.username}' already exists in panel")
            raise

    async def update_user(
        self,
        user: UserDto,
        user_id: int,
        plan: Optional[PlanSnapshotDto] = None,
        subscription: Optional[SubscriptionDto] = None,
        reset_traffic: bool = False,
    ) -> UserResponseDto:
        request_dto = self._build_update_request(user, user_id, plan, subscription)

        try:
            remna_user = await self.sdk.users.update_user(request_dto)
            logger.info(
                f"RemnaUser '{remna_user.username}' updated successfully. "
                f"id: '{remna_user.id}', telegram_id: '{remna_user.telegram_id}'"
            )
        except NotFoundError:
            logger.warning(
                f"RemnaUser '{request_dto.username}' with id '{request_dto.id}' not found"
            )
            raise

        if reset_traffic:
            await self.reset_traffic(user_id)

        return remna_user

    async def enable_user(self, user_id: int) -> None:
        try:
            await self.sdk.users.enable_user(user_id)
            logger.info(f"RemnaUser '{user_id}' enabled successfully")
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            raise

    async def disable_user(self, user_id: int) -> None:
        try:
            await self.sdk.users.disable_user(user_id)
            logger.info(f"RemnaUser '{user_id}' disabled successfully")
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            raise

    async def delete_user(self, user_id: int) -> bool:
        # Panel 3.0.0 answers 204 with no body, so success is simply the absence
        # of an error — there is no `isDeleted` flag to read anymore.
        try:
            await self.sdk.users.delete_user(user_id)
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return False

        logger.info(f"RemnaUser '{user_id}' deleted successfully")
        return True

    async def get_user_by_id(self, user_id: int) -> Optional[UserResponseDto]:
        try:
            remna_user = await self.sdk.users.get_user_by_id(user_id)
            logger.info(f"Fetched RemnaUser '{user_id}' from panel")
            return remna_user
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return None

    async def get_users_by_telegram_id(self, telegram_id: int) -> list[UserResponseDto]:
        users = await self._stream_users(telegram_id=telegram_id)
        logger.debug(f"Fetched {len(users)} RemnaUsers for telegram_id '{telegram_id}'")
        return users

    async def get_all_users(self, limit: int, offset: int) -> list[UserResponseDto]:
        response = await self.sdk.users.get_all_users(start=offset, size=limit)
        logger.debug(f"Fetched {len(response.users)} RemnaUsers (limit={limit}, offset={offset})")
        return response.users

    async def get_users_by_email(self, email: str) -> list[UserResponseDto]:
        users = await self._stream_users(email=email)
        logger.debug(f"Fetched {len(users)} RemnaUsers for email '{email}'")
        return users

    async def _stream_users(self, **filters: Any) -> list[UserResponseDto]:
        """Collect every user matching a filter from the cursor-paginated stream.

        Panel 3.0.0 removed the `by-telegram-id` / `by-email` / `by-tag` lookups;
        `/users/stream` with the same filters replaces them, so the cursor has to
        be walked to get the full result set.

        Walks to completion or raises, like :meth:`get_squad_usage` — a silently
        truncated list reads as "no such user" to every caller, which is worse than
        failing: it would recreate a user who already exists, or hand back an empty
        account lookup. A keyset cursor that stops moving is a panel bug rather than
        an end-of-stream signal, so it is caught outright instead of spun on.
        """
        users: list[UserResponseDto] = []
        cursor: Optional[int] = None
        page_number = 0

        while True:
            page = await self.sdk.users.get_users_stream(
                size=USERS_STREAM_PAGE_SIZE, cursor=cursor, **filters
            )
            users.extend(page.users)
            page_number += 1

            if not page.has_more or page.next_cursor is None:
                return users

            next_cursor = int(page.next_cursor)
            if next_cursor == cursor:
                raise RuntimeError(
                    f"Panel returned a non-advancing /users/stream cursor "
                    f"('{next_cursor}') for filters {filters}; refusing to loop"
                )
            if page_number >= USERS_STREAM_MAX_PAGES:
                raise RuntimeError(
                    f"/users/stream for filters {filters} exceeded "
                    f"{USERS_STREAM_MAX_PAGES} pages; refusing to act on a partial result"
                )

            cursor = next_cursor

    async def get_devices(self, user_id: int) -> list[HwidDeviceDto]:
        response = await self.sdk.hwid.get_hwid_user(user_id)
        logger.debug(f"Fetched {response.total} devices for RemnaUser '{user_id}'")
        return response.devices if response.total else []

    async def delete_device(self, user_id: int, hwid_uuid: str) -> Optional[int]:
        try:
            response = await self.sdk.hwid.delete_hwid_to_user(
                DeleteUserHwidDeviceRequestDto(user_id=user_id, hwid=hwid_uuid)
            )
            logger.info(
                f"Deleted HWID device '{hwid_uuid}' for RemnaUser '{user_id}'. "
                f"Total devices now: {response.total}"
            )
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return None

        return int(response.total)

    async def delete_all_devices(self, user_id: int) -> None:
        try:
            result = await self.sdk.hwid.delete_all_hwid_user(
                DeleteUserAllHwidDeviceRequestDto(user_id=user_id)
            )
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return
        logger.info(f"Deleted all HWID devices ({result.total}) for RemnaUser '{user_id}'")

    async def drop_connections(self, user_id: int) -> None:
        """Kill the user's live sessions on every node. Best effort, except for auth.

        A rejected token is not a transient hiccup: panel 3.0.0 renamed the scope
        behind this endpoint (``ip-control:*`` -> ``connections:drop``), and a token
        reissued without it fails *every* call. Absorbing that would let callers
        record a disconnect that never happened, so the auth family is re-raised —
        the device-reset use cases surface it through the bot's error middleware,
        and the pool cut refuses to mark itself done.

        Everything else (network blips, node errors) stays non-fatal: all three call
        sites have already committed the part that matters — the device is deleted,
        the squad is withdrawn — and a dropped session only outlives that until the
        client reconnects, which it can no longer do.
        """
        try:
            await self.sdk.connections.drop_connections(
                body=DropConnectionsRequestDto(
                    drop_by=DropByUserIds(user_ids=[user_id]),
                    target_nodes=TargetAllNodes(),
                )
            )
            logger.info(f"Dropped connections for RemnaUser '{user_id}'")
        except (AuthenticationError, UnauthorizedError, ForbiddenError) as e:
            # 403 is the runbook miss (token lacks `connections:drop`); 401 and the
            # AUTH* codes are an expired or revoked token. remnapy maps each to its
            # own sibling class, so all three have to be named.
            logger.error(
                f"Not authorised to drop connections for RemnaUser '{user_id}': {e}. "
                f"The panel API token must be valid and hold the 'connections:drop' "
                f"scope, which panel 3.0.0 renamed from 'ip-control:*'."
            )
            raise
        except Exception as e:
            logger.error(f"Failed to drop connections for RemnaUser '{user_id}': {e}")

    async def reset_traffic(self, user_id: int) -> Optional[UserResponseDto]:
        try:
            remna_user = await self.sdk.users.reset_user_traffic(user_id)
            logger.info(f"Traffic for RemnaUser '{remna_user.id}' reset successfully")
            return remna_user
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            return None

    async def revoke_subscription(self, user_id: int) -> None:
        try:
            await self.sdk.users.revoke_user_subscription(user_id)
            logger.info(f"Subscription for RemnaUser '{user_id}' revoked successfully")
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")

    async def set_user_expire(self, user_id: int, expire_at: datetime) -> None:
        """Patch only a RemnaUser's expiry (partial update).

        Used to (re)start the trial clock at first connection without touching any
        other field — Remnawave applies just the provided ``expire_at``.
        """
        try:
            await self.sdk.users.update_user(
                UpdateUserRequestDto(id=user_id, expire_at=expire_at)
            )
            logger.info(f"RemnaUser '{user_id}' expiry set to '{expire_at.isoformat()}'")
        except NotFoundError:
            logger.debug(f"RemnaUser '{user_id}' not found in panel")
            raise

    async def get_squads_available(self) -> bool:
        result = await self.sdk.internal_squads.get_internal_squads()
        return bool(result.internal_squads)

    async def get_internal_squads(self) -> list[SquadInfoDto]:
        result = await self.sdk.internal_squads.get_internal_squads()
        return [SquadInfoDto(uuid=s.uuid, name=s.name) for s in result.internal_squads]

    async def get_external_squads(self) -> list[SquadInfoDto]:
        result = await self.sdk.external_squads.get_external_squads()
        return [SquadInfoDto(uuid=s.uuid, name=s.name) for s in result.external_squads]

    async def get_squad_nodes(self, squad_uuid: UUID) -> list[PoolNodeDto]:
        """Nodes reachable through a squad's inbounds.

        Shown when an admin picks the squad behind a traffic pool: metering is per
        node, so this is the only way to see what the pool will actually measure —
        and to notice that a squad spans a free location by mistake.
        """
        result = await self.sdk.internal_squads.get_accessible_nodes(str(squad_uuid))
        return [
            PoolNodeDto(uuid=node.uuid, name=node.name, country_code=node.country_code or "")
            for node in result.accessible_nodes
        ]

    async def get_squad_usage(
        self,
        squad_uuid: UUID,
        start: datetime,
        end: datetime,
        min_total_bytes: int,
        page_size: int = 500,
    ) -> list[PoolUsageRowDto]:
        """Users whose usage on the squad's nodes reached ``min_total_bytes``.

        The threshold is applied server-side, so one request answers "who is over
        quota (and who is close)" for a whole pool instead of a per-user sweep. Walks
        the cursor to completion — the caller gets the full set or an exception, never
        a silently truncated one, because acting on a partial set would restore access
        for everyone the missing pages would have flagged.
        """
        rows: list[PoolUsageRowDto] = []
        cursor: Optional[Union[str, int]] = None
        page = 0

        while True:
            response = await self.sdk.bandwidthstats.get_internal_squad_usage(
                uuid=str(squad_uuid),
                start=start.strftime(PANEL_DATE_FORMAT),
                end=end.strftime(PANEL_DATE_FORMAT),
                min_total_bytes=min_total_bytes,
                limit=page_size,
                cursor=cursor,
            )
            rows.extend(
                PoolUsageRowDto(user_remna_id=item.id, total_bytes=item.total_bytes)
                for item in response.users
            )
            page += 1

            if not response.has_more or response.next_cursor is None:
                break
            if page >= SQUAD_USAGE_MAX_PAGES:
                raise RuntimeError(
                    f"Squad '{squad_uuid}' usage exceeded {SQUAD_USAGE_MAX_PAGES} pages; "
                    f"refusing to act on a partial result"
                )
            cursor = response.next_cursor

        logger.debug(
            f"Squad '{squad_uuid}' usage: '{len(rows)}' users over "
            f"'{min_total_bytes}' bytes in {page} page(s)"
        )
        return rows

    async def get_squad_user_usage(
        self,
        squad_uuid: UUID,
        user_id: int,
        start: datetime,
        end: datetime,
    ) -> int:
        """One user's exact total on a squad's nodes over the period.

        The threshold sweep above cannot answer this below its cut-off, so the surfaces
        that show a real number (the cabinet meter, the admin card) ask per user.
        """
        response = await self.sdk.bandwidthstats.get_internal_squad_user_usage(
            squad_uuid=str(squad_uuid),
            user_id=user_id,
            start=start.strftime(PANEL_DATE_FORMAT),
            end=end.strftime(PANEL_DATE_FORMAT),
        )
        return sum(node.total_bytes for day in response.days for node in day.nodes)

    def apply_sync(self, target: T, source: Union[SubscriptionDto, RemnaSubscriptionDto]) -> T:
        if not is_dataclass(target) or not is_dataclass(source):
            raise TypeError("Both target and source must be dataclasses")

        target_fields = {f.name for f in fields(target)}
        source_fields = {f.name for f in fields(source)}

        for target_field, source_field in SYNC_FIELD_MAP.items():
            if target_field in target_fields and source_field in source_fields:
                self._sync_field(target, target_field, getattr(source, source_field))

        # Everything else carries over by matching name. Fields already placed by
        # SYNC_FIELD_MAP are skipped here — their source name means something else on
        # the target — and so are the protected ones, which never come from the panel.
        common_fields = (
            (target_fields & source_fields)
            - set(SYNC_FIELD_MAP.values())
            - SYNC_PROTECTED_FIELDS
        )

        for field_name in common_fields:
            self._sync_field(target, field_name, getattr(source, field_name))

        return target

    @staticmethod
    def _sync_field(target: Any, field_name: str, new_value: Any) -> None:
        old_value = getattr(target, field_name)
        if old_value == new_value:
            return

        logger.debug(f"Field '{field_name}' changed from '{old_value}' to '{new_value}'")
        setattr(target, field_name, new_value)

    def _build_create_request(
        self,
        user: UserDto,
        plan: Optional[PlanSnapshotDto],
        subscription: Optional[SubscriptionDto],
    ) -> CreateUserRequestDto:
        if subscription:
            # Panel 3.0.0 no longer accepts a caller-supplied id on create, so a
            # recreated user gets a fresh one. Every caller of this branch follows
            # up with SyncRemnaUser, which writes the new id back to the local row.
            return CreateUserRequestDto(
                username=user.remna_name,
                telegram_id=user.telegram_id,
                expire_at=subscription.expire_at,
                traffic_limit_strategy=subscription.traffic_limit_strategy,
                traffic_limit_bytes=gb_to_bytes(subscription.traffic_limit),
                hwid_device_limit=subscription.device_limit,
                description=user.remna_description,
                email=user.email,
                tag=subscription.tag,
                active_internal_squads=subscription.internal_squads,
                external_squad_uuid=subscription.external_squad,
            )

        if plan:
            return CreateUserRequestDto(
                username=user.remna_name,
                telegram_id=user.telegram_id,
                expire_at=days_to_datetime(plan.duration),
                traffic_limit_strategy=plan.traffic_limit_strategy,
                traffic_limit_bytes=gb_to_bytes(plan.traffic_limit),
                hwid_device_limit=plan.device_limit,
                description=user.remna_description,
                email=user.email,
                tag=plan.tag,
                active_internal_squads=plan.internal_squads,
                external_squad_uuid=plan.external_squad,
            )

        return CreateUserRequestDto(
            username=user.remna_name,
            telegram_id=user.telegram_id,
            expire_at=datetime_now() + timedelta(days=3650),
            description=user.remna_description,
            email=user.email,
        )

    def _build_update_request(
        self,
        user: UserDto,
        user_id: int,
        plan: Optional[PlanSnapshotDto],
        subscription: Optional[SubscriptionDto],
    ) -> UpdateUserRequestDto:
        if subscription:
            return UpdateUserRequestDto(
                id=user_id,
                telegram_id=user.telegram_id,
                expire_at=subscription.expire_at,
                status=(
                    SubscriptionStatus.DISABLED
                    if subscription.status == SubscriptionStatus.DISABLED
                    else SubscriptionStatus.ACTIVE
                ),
                traffic_limit_strategy=subscription.traffic_limit_strategy,
                traffic_limit_bytes=gb_to_bytes(subscription.traffic_limit),
                hwid_device_limit=subscription.device_limit,
                description=user.remna_description,
                email=user.email,
                tag=subscription.tag,
                active_internal_squads=subscription.internal_squads,
                external_squad_uuid=subscription.external_squad,
            )

        if plan:
            return UpdateUserRequestDto(
                id=user_id,
                telegram_id=user.telegram_id,
                expire_at=days_to_datetime(plan.duration),
                status=SubscriptionStatus.ACTIVE,
                traffic_limit_strategy=plan.traffic_limit_strategy,
                traffic_limit_bytes=gb_to_bytes(plan.traffic_limit),
                hwid_device_limit=plan.device_limit,
                description=user.remna_description,
                email=user.email,
                tag=plan.tag,
                active_internal_squads=plan.internal_squads,
                external_squad_uuid=plan.external_squad,
            )

        raise ValueError("Either 'plan' or 'subscription' must be provided")
