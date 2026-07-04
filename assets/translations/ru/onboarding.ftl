# Guided onboarding funnel (see src/telegram/routers/onboarding/).
# Turned on/off at runtime via the Extra settings toggle (onboarding_enabled).

msg-onboarding-platform =
    <b>🚀 Подключим за минуту</b>

    На каком устройстве подключаемся?

msg-onboarding-setup =
    <b>Подключаемся за 3 шага 👇</b>

    <b>1️⃣ Установите Happ</b> — приложение, через которое работает VPN.
    → <a href="{ $store_link }">Скачать Happ для { $platform ->
        [ios] iPhone
        [android] Android
        [windows] Windows
        [mac] Mac
       *[other] вашего устройства
    }</a>

    <b>2️⃣ Добавьте конфигурацию</b> — одним тапом, настроится сама.
    → <a href="{ $import_url }">Открыть в Happ</a>

    <b>3️⃣ Включите и проверьте</b> — откройте сайт, который раньше не открывался.

    Не открылось по ссылке? Скопируйте её кнопкой ниже.

msg-onboarding-refresh-tip =
    <b>✅ Почти готово!</b>

    Один момент, который однажды выручит. Иногда блокировки усиливаются, и подключение перестаёт пробивать. Мы быстро выпускаем фикс, но Happ подтягивает его с задержкой.

    Чтобы не ждать: откройте Happ и нажмите «Обновить» (⟳) — приложение сразу подтянет свежую версию.

msg-onboarding-success =
    <b>🎉 Готово, вы в сети!</b>

    Доступ сохранён за вами. Кнопка подключения всегда доступна ниже и в главном меню.

msg-onboarding-help =
    <b>Чаще всего помогает 👇</b>

    • Откройте Happ и нажмите «Обновить» (⟳) — подтянутся свежие серверы.
    • В списке серверов выберите другую локацию или протокол.
    • Если не помогло — напишите в поддержку, поможем.

# Pre-connect nudge (delivered by the sweeper task).
event-onboarding-nudge =
    <b>Остался один шаг 🚀</b>

    Вы почти подключились — осталось добавить конфигурацию и проверить. Займёт минуту.

btn-onboarding =
    .nudge-open = 🚀 Продолжить подключение
    .platform-ios = 📱 iPhone
    .platform-android = 🤖 Android
    .platform-windows = 💻 Windows
    .platform-mac = 🍎 Mac
    .works = 🎉 Работает!
    .fail = 😕 Не получается
    .copy = 📋 Скопировать ссылку
    .understood = Понятно
    .refresh-video = ▶️ Как обновить (видео)
    .support = 💬 Поддержка
