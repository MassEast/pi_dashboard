#!/bin/sh
# MIT License
#
# Copyright (c) 2016 LoveBootCaptain (Stephan Ansorge)
# Additional changes (c) 2025 MassEast
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

### BEGIN INIT INFO
# Provides:          PiDashboard
# Required-Start:    $remote_fs $syslog $network
# Required-Stop:     $remote_fs $syslog
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: PiDashboard
# Description:       PiDashboard
### END INIT INFO


# TODO!!!


# Change the next lines to suit where you install your script and what you want to call it
DAEMON=/home/pi/pi_dashboard/PiDashboard.py
DAEMON_NAME=PiDashboard
VENV_PATH="/home/pi/pi_dashboard/venv"

# Activate the virtual environment
if [ -f "$VENV_PATH/bin/activate" ]; then
    . "$VENV_PATH/bin/activate"
else
    echo "Virtual environment not found at $VENV_PATH"
    exit 1
fi

# Add any command line options for your daemon here
DAEMON_OPTS=""

# This next line determines what user the script runs as.
# 'root' generally not recommended but necessary if you are using the Raspberry Pi GPIO from Python.
DAEMON_USER=pi

# The process ID of the script when it runs is stored here:
PIDFILE=/var/run/${DAEMON_NAME}.pid

. /lib/lsb/init-functions

# Load DISPLAY_BLANK from config.json
CONFIG_FILE="/home/pi/pi_dashboard/config.json"
DISPLAY_BLANK=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['TIMER']['DISPLAY_BLANK'])")

# Export DISPLAY and set xset parameters
export DISPLAY=:0
export XAUTHORITY=/home/pi/.Xauthority
xhost +SI:localuser:root
xset s $DISPLAY_BLANK $DISPLAY_BLANK
xset dpms $DISPLAY_BLANK $DISPLAY_BLANK $DISPLAY_BLANK

do_start () {
    log_daemon_msg "Starting system $DAEMON_NAME daemon"
    start-stop-daemon --start --background --pidfile ${PIDFILE} --make-pidfile --user ${DAEMON_USER} --chuid ${DAEMON_USER} --startas ${DAEMON} -- ${DAEMON_OPTS}
    log_end_msg $?
}
do_stop () {
    log_daemon_msg "Stopping system $DAEMON_NAME daemon"
    start-stop-daemon --stop --pidfile ${PIDFILE} --retry 10
    log_end_msg $?
}

case "$1" in

    start)
        do_start
        ;;

    stop)
        do_stop
        ;;

    restart|reload|force-reload)
        do_stop
        do_start
        ;;

    status)
        status_of_proc "$DAEMON_NAME" "$DAEMON" && exit 0 || exit $?
        ;;

    *)
        echo "Usage: /etc/init.d/$DAEMON_NAME {start|stop|restart|status}"
        exit 1
        ;;

esac
exit 0
