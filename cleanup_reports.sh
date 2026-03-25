#!/bin/bash
find /opt/scada/reports -type f -mmin +1440 -not -name .gitkeep -delete 2>/dev/null
