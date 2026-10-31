"""Reset inherited OOM protection and die if the supervisor disappears."""
import ctypes
import argparse
import os
from pathlib import Path
import signal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protected', action='store_true')
    parser.add_argument('parent', type=int)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    # Runs after setpriv changes UID, since setuid clears PR_SET_PDEATHSIG.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'PR_SET_PDEATHSIG')
    if os.getppid() != args.parent:
        return 1
    if not args.protected:
        Path('/proc/self/oom_score_adj').write_text('0')
        os.nice(5)
    os.execvp(args.command[0], args.command)


if __name__ == '__main__':
    raise SystemExit(main())
