"""Bitrix24 module — constants and channel names.

Pure constants, no imports from main SCADA code.
"""

# Redis PubSub channels (existing — module only LISTENS)
REDIS_CHANNEL_MAINTENANCE = "maintenance:alerts"
REDIS_CHANNEL_ALARMS = "alarms:new"
REDIS_CHANNEL_COMMANDS = "bitrix24:commands"

# Redis cache key prefixes
REDIS_EQUIPMENT_PREFIX = "bitrix24:equipment:"
REDIS_EQUIPMENT_INDEX = "bitrix24:equipment:_index"
REDIS_USER_PREFIX = "bitrix24:user:"

# Bitrix24 property codes (from IBLOCK_ID=68)
PROP_EQUIPMENT_TYPE = "PROPERTY_332"
PROP_MODEL = "PROPERTY_334"
PROP_SYSTEM_CODE = "PROPERTY_338"
PROP_RESPONSIBLE = "PROPERTY_340"
PROP_ACTIVE = "PROPERTY_342"
PROP_ACCOMPLICES = "PROPERTY_344"
PROP_AUDITORS = "PROPERTY_346"

# Bitrix24 list values
ACTIVE_YES_ID = "548"

# Alarm codes that trigger urgent Bitrix24 tasks
ALARM_CODES_URGENT = {"SHUTDOWN", "TRIP_STOP"}

# Maintenance severity levels that trigger Bitrix24 tasks
MAINTENANCE_SEVERITY_TASK = {"critical", "overdue"}

# Task title templates
TASK_TITLE_MAINTENANCE = "{interval_name} — {device_name} ({model})"
TASK_TITLE_ALARM = "АВАРИЯ: {alarm_code} — {device_name}"

# Bitrix24 task statuses that mean "closed"
B24_CLOSED_STATUSES = {"5", "6", "7"}  # 5=Completed, 6=Deferred, 7=Declined

# Cache TTL (seconds)
USER_CACHE_TTL = 86400  # 24 hours
