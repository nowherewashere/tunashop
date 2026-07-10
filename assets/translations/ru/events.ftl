event-error =
    .general =
    #ErrorEvent

    <b>🔅 Событие: Произошла ошибка!</b>

    { frg-build-info }
    
    { $telegram_id -> 
    [0] { space }
    *[HAS]
    { hdr-user }
    { frg-user-info }
    }

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .remnawave-version =
    #RemnawaveVersionWarningEvent

    <b>⚠️ Событие: Возможная несовместимость с Remnawave!</b>

    <blockquote>
    Версия панели <b>{ $panel_version }</b> выше протестированной версии <b>{ $max_version }</b>. Некоторые функции бота могут работать некорректно.
    </blockquote>

    { frg-build-info }
    
    .remnawave =
    #RemnawaveErrorEvent

    <b>🔅 Событие: Ошибка при подключении к Remnawave!</b>

    <blockquote>
    Без активного подключения корректная работа бота невозможна!
    </blockquote>

    { frg-build-info }

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .webhook =
    #ErrorEvent

    <b>🔅 Событие: Зафиксирована ошибка вебхука!</b>

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .channel-check =
    #ChannelCheckErrorEvent

    <b>⚠️ Событие: Ошибка проверки подписки на канал/группу!</b>

    { hdr-user }
    { frg-user-info }

    <blockquote>
    • <b>Причина</b>: <code>{ $reason }</code>
    </blockquote>
    
    Проверьте, что бот является администратором канала/группы с правом просмотра участников.

    .notification =
    #NotificationErrorEvent

    <b>⚠️ Событие: Ошибка доставки системного уведомления!</b>

    <blockquote>
    • <b>Маршрут</b>: { NUMBER($chat_id, useGrouping: 0) }{ $thread_id ->
        [0] { space }
        *[HAS] :{ NUMBER($thread_id, useGrouping: 0) }
    }
    • <b>Причина</b>: <code>{ $reason }</code>
    </blockquote>

    Проверьте маршрут уведомлений и убедитесь, что бот является участником группы с правами на отправку сообщений.


event-bot =
    .startup =
    #BotStartupEvent

    <b>🔅 Событие: Бот запущен!</b>

    { frg-build-info }

    <b>🔓 Доступность</b>
    <blockquote>
    • <b>Режим</b>: { access-mode }
    • <b>Платежи</b>: { $payments_allowed ->
    [0] запрещены
    *[1] разрешены
    }
    • <b>Регистрация</b>: { $registration_allowed ->
    [0] запрещена
    *[1] разрешена
    }
    </blockquote>

    .inline-mode-disabled =
    #BotInlineModeDisabledEvent

    <b>⚠️ Событие: Inline-режим отключен в BotFather!</b>

    <blockquote>
    Бот не настроен для работы в inline-режиме. Некоторые функции бота могут работать некорректно.

    Включите Inline Mode в BotFather: <b>@BotFather → /mybots → Bot Settings → Inline Mode → Enable</b>
    </blockquote>

    .shutdown =
    #BotShutdownEvent

    <b>🔅 Событие: Бот остановлен!</b>

    { frg-build-info }

    <blockquote>
    • <b>Аптайм</b>: { $uptime }
    </blockquote>

    .update =
    #BotUpdateEvent

    <b>🔅 Событие: Обнаружено обновление Remnashop!</b>

    <b>📑 Версии</b>
    <blockquote>
    • <b>Текущая</b>: { $local_version }
    • <b>Последняя</b>: { $remote_version }
    </blockquote>


event-user =
    .registered =
    #UserRegisteredEvent

    <b>🔅 Событие: Новый пользователь!</b>

    { hdr-user }
    { frg-user-info }

    { $referrer_user_id ->
    [0] { empty }
    *[HAS]
    <b>🤝 Пригласитель</b>
    <blockquote>
    { $referrer_telegram_id ->
        [0] • <b>Почта</b>: <code>{ $referrer_email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($referrer_telegram_id, useGrouping: 0) }</code>
    }
    • <b>Имя</b>: { $referrer_name } { $referrer_username ->
        [0] { empty }
        *[HAS] (<a href="tg://user?id={ $referrer_telegram_id }">@{ $referrer_username }</a>)
    }
    </blockquote>
    }

    { $ad_link_id ->
    [0] { empty }
    *[HAS]
    <b>🎯 Рекламная ссылка</b>
    <blockquote>
    • <b>Название</b>: { $ad_link_name }
    • <b>Код</b>: <code>{ $ad_link_code }</code>
    </blockquote>
    }

    .first-connected =
    #UserFirstConnectionEvent

    <b>🔅 Событие: Первое подключение пользователя!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-subscription }
    { frg-subscription-details }

    .device-added =
    #UserDeviceAddedEvent

    <b>🔅 Событие: Пользователь добавил новое устройство!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-hwid }
    { frg-user-hwid }

    .device-deleted =
    #UserDeviceDeletedEvent

    <b>🔅 Событие: Пользователь удалил устройство!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-hwid }
    { frg-user-hwid }


event-blacklist =
    .registration-attempt =
    #BlacklistRegistrationAttemptEvent

    <b>🔅 Событие: Попытка регистрации из черного списка!</b>

    { hdr-user }
    { frg-user-info }


event-subscription =
    .trial =
    #SubscriptionTrialEvent

    <b>🔅 Событие: Получение пробной подписки!</b>

    { hdr-user }
    { frg-user-info }
    
    { hdr-plan }
    { frg-plan-snapshot }
    
    .new =
    #SubscriptionNewEvent

    <b>🔅 Событие: Покупка подписки!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot }

    .renew =
    #SubscriptionRenewEvent

    <b>🔅 Событие: Продление подписки!</b>
    
    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot }

    .change =
    #SubscriptionChangeEvent

    <b>🔅 Событие: Изменение подписки!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot-comparison }

    .expiring =
    { $is_trial ->
    [0]
    <b>⚠️ Внимание! Твоя подписка закончится через { unit-day }.</b>

    Продли её заранее, чтобы не терять доступ к сервису!
    *[1]
    <b>⏳ Твой пробник заканчивается через { unit-day }.</b>

    Останься в сети без перерыва — оформи Standard 🐟
    }

    .expired =
    <b>⛔ Внимание! Доступ приостановлен — VPN не работает.</b>

    { $is_trial ->
    [0] Твоя подписка истекла — продли её, чтобы продолжить пользоваться VPN!
    *[1] Триал закончился 🐟 Вернуть доступ — один тап. Продолжим?
    }

    .expired-ago =
    <b>⛔ Внимание! Доступ приостановлен — VPN не работает.</b>

    { $is_trial ->
    [0] Твоя подписка истекла { unit-day } назад — продли её, чтобы продолжить пользоваться сервисом!
    *[1] Твой бесплатный пробный период закончился { unit-day } назад. Оформи подписку, чтобы продолжить пользоваться сервисом!
    }

    .limited =
    <b>⛔ Внимание! Доступ приостановлен — VPN не работает.</b>

    Твой трафик израсходован. { $is_trial ->
    [0] { $traffic_strategy ->
        [NO_RESET] Продли подписку, чтобы сбросить трафик и снова пользоваться сервисом!
        *[RESET] Трафик восстановится через { $reset_time }. Ещё можно продлить подписку, чтобы сбросить трафик.
        }
    *[1] { $traffic_strategy ->
        [NO_RESET] Оформи подписку, чтобы продолжить пользоваться сервисом!
        *[RESET] Трафик восстановится через { $reset_time }. Ещё можно оформить подписку, чтобы пользоваться сервисом без ограничений.
        }
    }

    .not-connected =
    <b>🔌 Не получилось подключиться?</b>

    Если возникли сложности с настройкой VPN — мы готовы помочь! Напиши в поддержку, и мы разберёмся вместе.

    .revoked =
    #SubscriptionRevokedEvent

    <b>🔅 Событие: Пользователь перевыпустил подписку!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-subscription }
    { frg-subscription-details }


event-node =
    .connection-lost =
    #NodeConnectionLostEvent
    
    <b>🔅 Событие: Соединение с узлом потеряно!</b>

    { hdr-node }
    { frg-node-info }

    .connection-restored =
    #NodeConnectionRestoredEvent

    <b>🔅 Событие: Соединение с узлом восстановлено!</b>

    { hdr-node }
    { frg-node-info }

    .traffic-reached =
    #NodeTrafficReachedEvent

    <b>🔅 Событие: Узел достиг порога лимита трафика!</b>

    { hdr-node }
    { frg-node-info }


event-torrent-blocker =
    .user-blocked =
    <b>⛔ Доступ на сервере временно ограничен.</b>

    На ноде <b>{ $node_name }</b> зафиксирован BitTorrent трафик.
    Ограничение будет действовать еще <b>{ $block_duration }</b>.

    Если нужна помощь с настройкой подключения — напиши в поддержку.

    .report =
    #TorrentBlockedEvent

    <b>⚠️ Событие: Обнаружен BitTorrent трафик!</b>

    { hdr-user }
    { frg-user-info }

    <blockquote>
    • <b>Нода</b>: { $node_name }
    • <b>IP</b>: <code>{ $blocked_ip }</code>
    • <b>Длительность блока</b>: { $block_duration }
    • <b>Разблокировка</b>: { $will_unblock_at }
    • <b>Протокол</b>: <code>{ $protocol }</code>
    • <b>Источник</b>: <code>{ $source }</code>
    • <b>Назначение</b>: <code>{ $destination }</code>
    </blockquote>


event-referral =
    .attached =
    <b>🎉 Ты пригласил друга!</b>

    <blockquote>
    Пользователь <b>{ $name }</b> присоединился по твоей ссылке! Чтобы получить награду, дождись, когда он оформит подписку.
    </blockquote>

    .reward =
    <b>💰 Тебе начислена награда!</b>

    <blockquote>
    Пользователь <b>{ $name }</b> совершил платёж. Ты получил { $reward_type ->
    [POINTS] <b>{ $value } { $value -> 
        [one] балл
        [few] балла
        *[more] баллов 
        }</b>

    <i>Чтобы использовать баллы, зайди в раздел «Пригласить» в боте — там доступные награды и способы их применения.</i>
    [EXTRA_DAYS] <b>{ $value } доп. { $value ->
        [one] день
        [few] дня
        *[more] дней
        }</b> к твоей подписке!
    *[OTHER] <b>{ $value } { $reward_type }</b>
    }
    </blockquote>

    .reward-failed =
    <b>❌ Не получилось выдать награду!</b>
    
    <blockquote>
    Пользователь <b>{ $name }</b> совершил платёж, но мы не смогли начислить тебе вознаграждение, потому что <b>у тебя нет купленной подписки</b>, к которой можно было бы добавить { $value } { $reward_type ->
    [POINTS] { $value -> 
        [one] балл
        [few] балла
        *[more] баллов 
        }
    [EXTRA_DAYS] доп. { $value -> 
        [one] день
        [few] дня
        *[more] дней
        }
    *[OTHER] { $reward_type }
    }.
    
    <i>Купи подписку, чтобы получать бонусы за приглашённых друзей!</i>
    </blockquote>

event-payout =
    .processing =
    <b>⏳ Вывод в обработке</b>

    <blockquote>
    Твой вывод { $amount } ₽ в обработке.
    </blockquote>

    .paid =
    <b>💸 Готово! Вывод выполнен</b>

    <blockquote>
    { $amount } ₽ отправлены на { $wallet }.
    Хэш: <code>{ $tx_hash }</code>
    </blockquote>

    .paid-stars =
    <b>⭐ Готово! Stars начислены</b>

    <blockquote>
    Начислили { $stars } ⭐ на твой Telegram. Трать внутри Telegram.
    </blockquote>

    .rejected =
    <b>⚠️ Вывод отклонён</b>

    <blockquote>
    Вывод { $amount } ₽ отклонён: { $reason }.
    Баланс вернулся — { $balance } ₽. Проверь данные и попробуй снова.
    </blockquote>

event-promocode =
    .activated =
    #PromocodeActivatedEvent

    <b>🔅 Событие: Активация промокода!</b>

    { hdr-user }
    { frg-user-info }

    <b>🎟 Промокод</b>
    <blockquote>
    • <b>Код</b>: <code>{ $promocode_code }</code>
    • <b>Тип</b>: { promocode-type }
    • <b>Награда</b>: { frg-promocode-reward }
    </blockquote>

event-payment =
    .refunded =
    #PaymentRefundedEvent

    <b>⚠️ Событие: Платеж возвращен!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    Требуется ручная проверка — подписка пользователя могла остаться активной.

    .referral-failed =
    <b>⚠️ Не удалось начислить реферальную награду</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    Покупка завершена успешно, но при начислении реферальной награды произошла ошибка. Требуется ручная проверка.

    .purchase-failed =
    <b>⚠️ Событие: Ошибка обработки платежа!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    Платеж получен, но не удалось выдать подписку. Транзакция помечена как FAILED. Требуется ручная проверка.

event-remnashop-welcome =
    <b>💎 Remnashop v{ $version }</b>

    Проект создан и поддерживается всего одним <strike>разработчиком</strike> электриком. Поскольку бот полностью БЕСПЛАТНЫЙ и имеет открытый исходный код, он существует только благодаря вашей поддержке.

    ⭐ <i>Поставьте звездочку на <a href="{ $repository }">GitHub</a> и присоединяйтесь к нашему <a href="https://t.me/@remna_shop">сообществу</a>.</i>

    🎁 <i>Также есть <a href="https://boosty.to/snoups/purchase/3778398?ssource=DIRECT&amp;share=subscription_link">приватный чат</a> для донатеров.</i>
