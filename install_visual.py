#!/usr/bin/env python3
"""Install the optional Lithos/Signal web view without discarding the numeric CLI."""
import argparse
import os
import re
from pathlib import Path
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
INSERT_ARGS = '''    parser.add_argument(
        "--web", action="store_true",
        help="Serve the animated Lithos / Signal browser dashboard"
    )
    parser.add_argument(
        "--numeric", action="store_true",
        help="Keep the original numeric terminal dashboard (default)"
    )
    parser.add_argument(
        "--web-port", type=int, default=8787,
        help="TCP port for --web (default: 8787)"
    )
    parser.add_argument(
        "--web-listen", default="127.0.0.1",
        help="Web bind address, e.g. 192.168.1.9 (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--web-interval", type=int, default=5,
        help="Sampling seconds for --web (default: 5)"
    )

'''
INSERT_HANDLER = '''    if args.web and args.numeric:
        parser.error("--web and --numeric cannot be combined")
    if args.web:
        from lithos_web import main as lithos_web_main
        return lithos_web_main([
            "--url", args.url,
            "--days", str(args.days),
            "--port", str(args.web_port),
            "--listen", args.web_listen,
            "--interval", str(args.web_interval),
        ])

'''

# Adjust only the presentation layer; the original payout model stays authoritative.
# This addition is deliberately guarded so the numerical dashboard keeps running
# on older Lithos clients and offline machines without a DEX/USD price feed.
INCOME_ANCHOR = '''    render_income_projection(
        income_model, terminal_columns >= WIDE_LAYOUT_MIN_COLUMNS
    )
'''
INCOME_ADDENDUM = '''    try:
        from lithos_pricing import price_income, numeric_lines
        lit_market = price_income(sys.modules[__name__], base, income_model, height=source_height)
        print()
        print(col("  LIT / ERG / USD MARKET VALUATION (INDICATIVE)", BOLD, CYAN))
        for lit_line in numeric_lines(lit_market):
            print(col(lit_line, CYAN if lit_market.get("available") else YELLOW))
    except Exception as market_exc:
        print(col("  LIT market price temporarily unavailable: " + type(market_exc).__name__, YELLOW))
'''


def upgrade_web_launcher(text):
    """Add v0.2.1's LAN option to an already-patched v0.2.0 launcher.

    The visual launcher is installed only once; later upgrades must migrate its
    option parser and forwarded arguments without reinserting --web itself.
    """
    if 'from lithos_web import main as lithos_web_main' not in text:
        return text
    option = '"--web-listen"'
    forwarding = '"--listen", args.web_listen,'
    if option not in text:
        anchor = '''    parser.add_argument(
        "--web-interval",'''
        if text.count(anchor) != 1:
            raise ValueError('Cannot locate the previous --web-interval argument')
        new_arg = '''    parser.add_argument(
        "--web-listen", default="127.0.0.1",
        help="Web bind address (default: 127.0.0.1)"
    )
'''
        text = text.replace(anchor, new_arg + anchor, 1)
    if forwarding not in text:
        anchor = '''            "--port", str(args.web_port),
'''
        if text.count(anchor) != 1:
            raise ValueError('Cannot locate previous --web argument forwarding')
        text = text.replace(anchor, anchor + '            "--listen", args.web_listen,\n', 1)
    return text


def add_lit_valuation(text):
    if 'from lithos_pricing import price_income, numeric_lines' in text:
        return text
    if INCOME_ANCHOR not in text:
        return text
    out = text.replace(INCOME_ANCHOR, INCOME_ANCHOR + '\n' + INCOME_ADDENDUM, 1)
    out = out.replace('bond refunds excluded; LIT has no USD valuation.',
                      'bond refunds excluded; LIT market value is indicative.')
    return out



def patch_target(target):
    if not target.is_file():
        raise FileNotFoundError(f'Existing lithos_dashboard not found: {target}')
    original = target.read_text(encoding='utf-8')
    if 'def main():' not in original or 'def api_get(' not in original:
        raise ValueError('Target is not the expected upstream lithos_dashboard executable')
    installed = 'from lithos_web import main as lithos_web_main' in original
    changed = original
    if not installed:
        anchor = '    args = parser.parse_args()\n'
        if original.count(anchor) != 1:
            raise ValueError('Cannot safely identify the argparse insertion point')
        changed = changed.replace(anchor, INSERT_ARGS + anchor + INSERT_HANDLER, 1)
    else:
        changed = upgrade_web_launcher(changed)
    changed = add_lit_valuation(changed)
    changed = re.sub(r'(?m)^VERSION\s*=\s*["\']0\.1\.4["\']$', 'VERSION = "0.2.1"', changed)
    changed = changed.replace('VERSION = "0.2.0"', 'VERSION = "0.2.1"')
    if '© 2026 Arcadian Computers, LLC · MIT License' not in changed:
        changed = changed.replace('  Ctrl-C exits. Values update in place.',
            '  © 2026 Arcadian Computers, LLC · MIT License | Ctrl-C exits. Values update in place.')
    if changed != original:
        # Existing installations may already have the v0.2.1 pricing backup.
        # Keep it and make a separate rollback point for this option hotfix.
        suffix = ('.before_visual' if not installed else
                  '.before_web_listen' if 'from lithos_pricing import price_income' in original else
                  '.before_lit_valuation')
        backup = target.with_name(target.name + suffix)
        if backup.exists():
            raise FileExistsError(f'Refusing to overwrite existing backup: {backup}')
        shutil.copy2(target, backup)
        fd, temp_path = tempfile.mkstemp(prefix=target.name + '.new.', dir=str(target.parent))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(changed)
            os.chmod(temp_path, target.stat().st_mode & 0o777)
            os.replace(temp_path, target)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        print(f'Patched {target} (backup: {backup})')
    else:
        print(f'Already patched: {target}')

    root = target.parent
    shutil.copy2(HERE / 'lithos_web.py', root / 'lithos_web.py')
    shutil.copy2(HERE / 'lithos_pricing.py', root / 'lithos_pricing.py')
    (root / 'lithos_web_assets').mkdir(exist_ok=True)
    shutil.copy2(HERE / 'lithos_web_assets' / 'index.html', root / 'lithos_web_assets' / 'index.html')
    print(f'Installed web files alongside {target}')


def update_readme(repo):
    readme = repo / 'README.md'
    if not readme.is_file():
        return
    marker = '## Graphical dashboard (v0.2.1)'
    content = readme.read_text(encoding='utf-8')
    if marker in content:
        return
    addition = """

## Graphical dashboard (v0.2.1)

This MIT-licensed dashboard is authored by **Arcadian Computers, LLC**.

- `lithos_dashboard --web --web-listen 192.168.1.9` starts the animated
  browser dashboard on that LAN interface (TCP 8787 by default).
- `lithos_dashboard --numeric` retains the original full numeric terminal view.
- `lithos_dashboard` defaults to the numeric terminal view.
- The browser also offers a Visual / Numbers toggle, live charts, NISP
  reliability, collateral utilization, confirmed rewards and conditional
  monthly income projections.
- LIT valuation uses the **Ergo mainnet LIT** liquidity pool and a read-only
  swap simulation, plus a fresh ERG/USD rate when available. Estimates are
  not guaranteed cash proceeds, and unverified prices show as unavailable.

For installation, LAN security, economic methodology, and rollback steps,
see [Visual Dashboard documentation](README_VISUAL.md). The browser service
has **no web authentication**; restrict TCP 8787 to trusted LAN hosts.
"""
    readme.write_text(content.rstrip() + addition, encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description='Install optional Lithos/Signal browser view')
    ap.add_argument('--target', default='/usr/local/sbin/lithos_dashboard', help='Installed CLI executable to extend')
    ap.add_argument('--repo', help='Additionally extend the source repository lithos_dashboard file')
    args = ap.parse_args()
    paths = [Path(args.target)]
    if args.repo:
        repo = Path(args.repo) / 'lithos_dashboard'
        if repo.resolve() not in {x.resolve() for x in paths}:
            paths.append(repo)
    for target in paths:
        patch_target(target)
    if args.repo:
        root = Path(args.repo)
        update_readme(root)
        shutil.copy2(HERE / 'README_VISUAL.md', root / 'README_VISUAL.md')
        shutil.copy2(HERE / 'RELEASE_NOTES.md', root / 'RELEASE_NOTES.md')
        shutil.copy2(HERE / 'install_visual.py', root / 'install_visual.py')
        (root / 'tests').mkdir(exist_ok=True)
        shutil.copy2(HERE / 'tests' / 'test_visual.py', root / 'tests' / 'test_visual.py')
        ignore = root / '.gitignore'
        if ignore.is_file():
            current = ignore.read_text(encoding='utf-8')
            additions = ['*.before_visual', '*.before_lit_valuation', '*.before_lan', '*.before_web_listen']
            missing = [pattern for pattern in additions if pattern not in current.splitlines()]
            if missing:
                ignore.write_text(current.rstrip() + '\n' + '\n'.join(missing) + '\n', encoding='utf-8')
    print('Use: lithos_dashboard --web --web-listen 192.168.1.9')
    print('Or:  lithos_dashboard --numeric   (also the default)')

if __name__ == '__main__':
    main()
