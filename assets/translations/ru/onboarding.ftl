# Guided onboarding funnel — screens + copy ported 1:1 from the Tuna idea bot
# (Belovitc/-LEGACY-TunaTGBot, onboarding router after its rebase onto the
# Remnashop engine). Flow: device choice → connect (or TV connect) → tips →
# success, plus a "не получается" self-service branch.
# Toggled on/off at runtime via the Extra settings (onboarding_enabled).
#
# Our fork keeps its own pre-connect nudge chain on top of these screens — the
# event-onboarding-nudge-* messages and the btn-onboarding.nudge-* / .connect
# keys below are ours (consumed by the nudge sweeper), not from the idea bot.

# Device choice — funnel entry
msg-onboarding-device =
    <b>🚀 Подключаемся</b>

    Выбери свое устройство ниже 👇

# 3-step guided connect (phone / desktop)
msg-onboarding-connect =
    <b>Подключаемся за 3 шага 👇</b>

    <b>1️⃣ Установи Happ</b>
    <blockquote>
    Приложение, через которое работает VPN.
    Кнопка «<b>{ btn-onboarding.store }</b>» ниже.
    </blockquote>

    <b>2️⃣ Добавь Tuna</b>
    <blockquote>
    Нажми кнопку «<b>{ btn-onboarding.open }</b>» ниже.
    Если не сработало — скопируй ссылку и добавь её в Happ вручную.
    </blockquote>

    <b>Ссылка:</b> <code>{ $subscription_url }</code>

    <b>3️⃣ Включи и проверь</b>
    <blockquote>
    Открывай недоступные сайты и свободно пользуйся интернетом.
    </blockquote>

    <i>Получилось? 🐟</i>

# TV connect — phone/web import (no direct deep link)
msg-onboarding-tv =
    { $platform ->
    [apple_tv]
    <b>📺 Apple TV</b>

    На ТВ нельзя добавить подписку ссылкой — её переносят с телефона. Делается так 👇

    1️⃣ Установи <b>Happ</b> на Apple TV из App Store.
    2️⃣ Запусти Happ на ТВ — откроется экран импорта.
    3️⃣ Перенеси подписку с телефона одним из способов:
    <blockquote>
    • <b>По Wi-Fi:</b> открой Happ на телефоне в той же сети и отсканируй QR-код с экрана ТВ → выбери подписку → подтверди.
    • <b>Веб-импорт:</b> на ТВ выбери «Web Import», зайди на <b>tv.happ.su</b>, введи код с экрана, вставь свою ссылку и нажми «Отправить».
    </blockquote>
    4️⃣ Готово — список серверов появится на главном экране.
    *[android_tv]
    <b>📺 Android TV / Google TV</b>

    На ТВ нельзя добавить подписку ссылкой — её переносят с телефона. Делается так 👇

    1️⃣ Установи <b>Happ</b> на ТВ из Google Play (или APK).
    2️⃣ Запусти Happ на ТВ — он предложит добавить подписку по локальной сети через QR.
    3️⃣ Отсканируй QR-код приложением <b>Happ</b> на телефоне — подписка перенесётся на ТВ.
    }

    <b>Важно:</b> Если по Wi-Fi не вышло — выбери «Web Import», зайди на <b>tv.happ.su</b>, введи код и вставь свою ссылку.

    🔗 Твоя ссылка для веб-импорта (нажми, чтобы скопировать):

    <code>{ $subscription_url }</code>

    📖 Пошаговая инструкция со скриншотами — по кнопке ниже.

# Refresh tip (shown after "Работает!")
msg-onboarding-tips =
    ✅ <b>Готово!</b> И один совет, который однажды тебя выручит 🐟

    Иногда цифровой шторм усиливается, и подключение перестаёт работать. Мы быстро выпускаем фикс — но Happ подтягивает его с задержкой.

    Чтобы не ждать: открой Happ и нажми «Обновить» (↻) — он сразу подтянет свежую версию.

    → <a href="{ $refresh_video_url }">Видео: как обновить за 5 секунд</a>

# Alert shown when a user taps "Работает!" before actually connecting (spec fix #18).
onboarding-not-connected-yet = 🐟 Похоже, ты ещё не в сети. Добавь Tuna в Happ, включи VPN и открой любой сайт — потом жми «Работает!». Только что подключился? Подожди пару секунд и попробуй снова.

# "Не получается" — self-service branch
msg-onboarding-fail =
    <b>Чаще всего помогает 👇</b>

    <blockquote>
    → Открой Happ и нажми <b>«Обновить» (⟳)</b> — подтянет свежие сервера
    → Смени локацию в Happ
    → Переподключись: скопируй ссылку заново и добавь в Happ
    </blockquote>

    Не помогло? Напиши в поддержку 🐟

# Pre-connect nudges (A-chain), delivered by the sweeper task — one per step.
# Ours, not from the idea bot.
event-onboarding-nudge-1 =
    <b>Застрял на подключении?</b>

    Это занимает минуту 🐟 — помогу с любого шага.
event-onboarding-nudge-2 =
    <b>Happ установлен, но VPN не подключился?</b>

    Часто помогает прямая ссылка 👇
event-onboarding-nudge-3 =
    <b>Твой пробный доступ ждёт.</b>

    Подключим за минуту? 🐟

btn-onboarding =
    .platform-ios = 📱 iPhone / Mac
    .platform-android = 🤖 Android
    .platform-windows = 💻 Windows
    .platform-linux = 🐧 Linux
    .platform-appletv = 📺 Apple TV
    .platform-androidtv = 📺 Android TV / Google TV
    .faq = 📖 Инструкция со скриншотами
    .web-import = 🌐 Веб-импорт (tv.happ.su)
    .store = ⬇️ Happ для { $platform_title }
    .store-global = ⬇️ Happ (App Store вне РФ)
    .store-ru = ⬇️ Happ (App Store РФ)
    .open = ➕ Добавить Tuna VPN
    .copy-link = 📋 Скопировать ссылку Happ
    .works = 🎉 Работает!
    .fail = 😕 Не получается
    .tips-ok = Понятно
    .connect = 🚀 Подключиться
    .nudge-continue = ▶️ Продолжить
    .nudge-fail = 🆘 Не получается
    .nudge-open-happ = ⚡ Открыть в Happ
    .nudge-connect = ⚡️ Подключиться
    .nudge-help = 💬 Помощь
