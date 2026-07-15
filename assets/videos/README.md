# Videos

Screen-recording clips shown inside the bot dialogs.

## `refresh_video.<ext>`

The "how to refresh in Happ" clip shown on the onboarding **tips** screen
(`Onboarding.TIPS`). Drop a file named `refresh_video.mp4` (or `.mov` / `.webm`)
here.

- Present → the tips screen shows a **▶️ Видео: как обновить** button; tapping it
  replaces the success banner with the playing clip.
- Absent → the button is hidden and the screen keeps the success banner (no break).

Resolution order (first match wins): `assets/videos/` then `assets.default/videos/`
— see `resolve_refresh_video()` in
`src/telegram/routers/onboarding/getters.py`.
