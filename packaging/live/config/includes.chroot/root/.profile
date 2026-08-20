# Beamo Wipe live session
if [ "$(tty 2>/dev/null)" = "/dev/tty1" ] && [ -z "${DISPLAY:-}" ]; then
  if command -v startx >/dev/null 2>&1; then
    # If X hangs on probe (common in VMs), fall back to the keyboard wizard.
    timeout 90 startx /usr/local/bin/beamo-wipe -- -nolisten tcp \
      || /usr/local/bin/beamo-wipe --console
  else
    /usr/local/bin/beamo-wipe --console
  fi
fi
