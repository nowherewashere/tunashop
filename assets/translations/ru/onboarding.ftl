# Guided onboarding funnel — screens ported 1:1 from the Tuna source bot
# (handlers/onboarding.py O0–O4 + the "Не получается" branch).
# Toggled on/off at runtime via the Extra settings (onboarding_enabled).
# The platform title and the video line come from the getter as pre-formatted
# variables ($platform_title, $video_block) to keep the copy byte-exact.

# O0 — entry
msg-onboarding-entry = Подключим за 1 минуту. Поехали 🐟

# O1 — device choice
msg-onboarding-platform = На каком устройстве подключаемся?

# O2 — the 3-step setup
msg-onboarding-setup =
    Подключаемся за 3 шага 👇

    1️⃣ Установить <b>Happ</b> — приложение, через которое работает VPN
       → <a href="{ $store_link }">Скачать Happ для { $platform_title }</a>

    2️⃣ Добавить <b>Tuna</b> — одним тапом, настроится само
       → <a href="{ $import_url }">Открыть в Happ</a>
       Не открылось? → Скопировать ссылку
       <code>{ $import_url }</code>

    3️⃣ Включить и проверить — открой сайт, что не открывался

# O3 — manual-refresh tip
msg-onboarding-refresh-tip =
    ✅ <b>Готово!</b> И один момент, который однажды тебя выручит 🐟

    Иногда РКН усиливает блокировки, и подключение перестаёт пробивать. Мы быстро выпускаем фикс — но Happ подтягивает его с задержкой.

    Чтобы не ждать: открой Happ и нажми «Обновить» (⟳) — он сразу подтянет свежую версию.{ $video_block }

# O4 — success
msg-onboarding-success =
    Готово, ты в сети ✓ 🐟
    Доступ сохранён за тобой.

# "Не получается" — self-service branch
msg-onboarding-help = Чаще всего помогает 👇

# "Сменить локацию" — shown as a popup alert (show_alert), not a screen.
msg-onboarding-change-location = В Happ открой список серверов и выбери другую локацию/протокол 🐟

# Manual config refresh screen (from the "Обновить в Happ" button)
msg-onboarding-refresh-happ =
    🔄 <b>Обновить в Happ</b>

    Открой Happ и нажми «Обновить» (⟳) — он подтянет свежие сервера. Это занимает пару секунд.{ $video_block }

# Pre-connect nudges (A-chain), delivered by the sweeper task — one per step.
event-onboarding-nudge-1 = Застрял на подключении? 🐟 Это занимает минуту — помогу с любого шага.
event-onboarding-nudge-2 = Happ поставился, но Tuna не добавился? Часто помогает прямая ссылка 👇
event-onboarding-nudge-3 = Твой пробный доступ ждёт. Подключим за минуту?

btn-onboarding =
    .connect = 🚀 Подключиться
    .platform-ios = 📱 iPhone
    .platform-android = 🤖 Android
    .platform-windows = 💻 Windows
    .platform-mac = 🍎 Mac
    .works = 🎉 Работает!
    .fail = 😕 Не получается
    .understood = Понятно
    .open-menu = Открыть меню
    .back-menu = ⬅️ В меню
    .refresh-happ = 🔄 Обновить в Happ (⟳)
    .change-location = 🌍 Сменить локацию
    .support = 💬 Поддержка
    .nudge-continue = ▶️ Продолжить
    .nudge-fail = 🆘 Не получается
    .nudge-open-happ = ⚡ Открыть в Happ
    .nudge-help = 💬 Помощь
