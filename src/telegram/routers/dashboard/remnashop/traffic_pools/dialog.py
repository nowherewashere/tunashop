from uuid import UUID

from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.style import Style
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.keyboards import main_menu_button
from src.telegram.states import DashboardRemnashop, RemnashopTrafficPools
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate
from src.telegram.widgets.kbd import Button, Column, ListGroup, Row, Select, Start, SwitchTo

from .getters import (
    configurator_getter,
    name_getter,
    nodes_getter,
    pools_getter,
    squad_getter,
)
from .handlers import (
    on_active_toggle,
    on_name_input,
    on_pool_confirm,
    on_pool_create,
    on_pool_delete,
    on_pool_select,
    on_squad_select,
)

pools = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-pools-main"),
    Row(
        Button(
            text=I18nFormat("btn-pools.create"),
            id="create",
            on_click=on_pool_create,
        ),
    ),
    ListGroup(
        Row(
            Button(
                text=I18nFormat(
                    "btn-pools.title",
                    name=F["item"]["name"],
                    squad=F["item"]["squad"],
                    is_active=F["item"]["is_active"],
                ),
                id="pool_select",
                on_click=on_pool_select,
            ),
        ),
        id="pools_list",
        item_id_getter=lambda item: item["id"],
        items="pools",
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardRemnashop.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=RemnashopTrafficPools.MAIN,
    getter=pools_getter,
)

configurator = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-pool-configurator"),
    Row(
        Button(
            text=I18nFormat("btn-pools.active-toggle", is_active=F["is_active"]),
            id="active_toggle",
            on_click=on_active_toggle,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-pools.name"),
            id="name",
            state=RemnashopTrafficPools.NAME,
        ),
        SwitchTo(
            text=I18nFormat("btn-pools.squad"),
            id="squad",
            state=RemnashopTrafficPools.SQUAD,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-pools.nodes"),
            id="nodes",
            state=RemnashopTrafficPools.NODES,
            when=F["has_squad"],
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-pools.save"),
            id="save",
            on_click=on_pool_confirm,
            style=Style(ButtonStyle.SUCCESS),
        ),
        Button(
            text=I18nFormat("btn-pools.delete"),
            id="delete",
            on_click=on_pool_delete,
            style=Style(ButtonStyle.DANGER),
            when=F["is_edit"],
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopTrafficPools.MAIN,
            mode=StartMode.RESET_STACK,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopTrafficPools.CONFIGURATOR,
    getter=configurator_getter,
)

name = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-pool-name"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopTrafficPools.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_name_input),
    IgnoreUpdate(),
    state=RemnashopTrafficPools.NAME,
    getter=name_getter,
)

squad = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-pool-squad"),
    Column(
        Select(
            text=I18nFormat(
                "btn-common.squad-choice",
                name=F["item"]["name"],
                selected=F["item"]["selected"],
            ),
            id="squad_select",
            item_id_getter=lambda item: item["uuid"],
            items="squads",
            type_factory=UUID,
            on_click=on_squad_select,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopTrafficPools.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopTrafficPools.SQUAD,
    getter=squad_getter,
)

nodes = Window(
    Banner(BannerName.DASHBOARD),
    I18nFormat("msg-pool-nodes"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=RemnashopTrafficPools.CONFIGURATOR,
        ),
    ),
    IgnoreUpdate(),
    state=RemnashopTrafficPools.NODES,
    getter=nodes_getter,
)

router = Dialog(
    pools,
    configurator,
    name,
    squad,
    nodes,
)
