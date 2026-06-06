"""btc_kalshi.diag — ask KALSHI directly what actually happened. No guessing:
balance, open positions, recent ORDERS (with real status), recent FILLS,
settlements, and the live market. Run on your Mac (it can reach Kalshi):

    cd ~/Desktop/BTCAgents && source venv/bin/activate
    python -m btc_kalshi.diag
"""
from __future__ import annotations

from . import kalshi, config as cfg, contract_context


def main():
    kid, pk, prod_id, prod_key, base, acct = cfg.get_credentials()
    print("=" * 60)
    print(f"ACTIVE ACCOUNT : {acct}  ({'DEMO' if acct == 2 else 'REAL'})")
    print(f"ORDER ENDPOINT : {base}")
    print(f"credentials loaded: key_id={'yes' if kid else 'NO'}  pem={'yes' if pk else 'NO'}")
    print("=" * 60)

    bal = kalshi.get_balance()
    print(f"\nBALANCE: {('$%.2f' % bal) if bal is not None else 'ERROR / None'}")

    pos = kalshi.get_positions()
    print(f"\nOPEN POSITIONS ({len(pos)}):")
    if not pos:
        print("  (none — nothing is currently held)")
    for p in pos:
        n = p.get("position", 0)
        if n:
            print(f"  {p.get('ticker')}: {'YES' if n>0 else 'NO'} x{abs(n)}  "
                  f"(exposure {p.get('market_exposure')}, realized {p.get('realized_pnl')})")

    orders, oerr = kalshi.get_orders(20)
    print(f"\nRECENT ORDERS ({len(orders)}){'  ERROR: '+oerr if oerr else ''}:")
    for o in orders[:12]:
        print(f"  {o.get('created_time','')[:19]}  {o.get('ticker')}  {o.get('action')} {o.get('side')} "
              f"x{o.get('count')}  status={o.get('status')}  "
              f"yes_px={o.get('yes_price')} no_px={o.get('no_price')}  "
              f"remaining={o.get('remaining_count')}")
    if not orders and not oerr:
        print("  (no orders on record for this account)")

    fills, ferr = kalshi.get_fills(20)
    print(f"\nRECENT FILLS ({len(fills)}){'  ERROR: '+ferr if ferr else ''}:")
    for f in fills[:12]:
        print(f"  {f.get('created_time','')[:19]}  {f.get('ticker')}  {f.get('side')} "
              f"x{f.get('count')} @ {f.get('yes_price') or f.get('no_price')}  "
              f"(is_taker={f.get('is_taker')})")
    if not fills and not ferr:
        print("  (NOTHING has filled on this account)")

    setts = kalshi.get_settlements(10)
    print(f"\nRECENT SETTLEMENTS ({len(setts)}):")
    for s in setts[:8]:
        print(f"  {s.get('settled_time','')[:19]}  {s.get('ticker')}  "
              f"revenue={s.get('revenue')}  yes={s.get('yes_count')} no={s.get('no_count')}")

    m = contract_context.get_contract()
    print("\nLIVE FRONT MARKET:")
    print(f"  {m}" if m else "  (none / not reachable)")
    print("\n" + "=" * 60)
    print("Read this top to bottom: if FILLS is empty, no order ever executed —")
    print("the bot's orders rested unfilled. ORDERS status tells you why.")


if __name__ == "__main__":
    main()
