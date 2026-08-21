# live-config 0140-xinit would write an infinite `startx` loop on tty1
# that never returns, so ~/.profile would never start Beamo Wipe.
# This file occupies that path so live-config will not overwrite it.
# The kiosk is launched from /root/.profile.
