# Metrics & analytics layer (metrics spec §6.5). A separate file so the single
# health-alert key never collides with the shared events.ftl. { $detail } is a
# pre-formatted, multi-line breakdown built by ComputeNodeHealth — passed as a
# raw variable exactly like ErrorEvent's { $error }.

event-metrics-health-alert =
    <b>🚨 Событие: Деградация связи на узле!</b>

    За последние { $window } мин success rate опустился ниже { $threshold }%:

    <blockquote>
    { $detail }
    </blockquote>
