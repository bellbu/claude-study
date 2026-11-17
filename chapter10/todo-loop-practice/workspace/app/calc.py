"""주문 금액 계산 모듈."""

import os


def subtotal(items):
    """(이름, 단가, 수량) 목록의 상품 합계를 반환한다."""
    return sum(price * quantity for _, price, quantity in items)


def apply_coupon(total, code):
    # ① TODO ID는 tasks.toml의 작업과 연결한다.
    if code != "WELCOME10":
        return total
    return (total * 9 // 10) // 100 * 100


def shipping_fee(total):
    return 0 if total >= 50_000 else 3_000


def get_exchange_rate(currency):
    # TODO[CALC-003]: EXPECTED_USD_RATE의 승인값을 USD에 적용한다.
    return None


def order_total(items, coupon=None):
    total = apply_coupon(subtotal(items), coupon)
    return total + shipping_fee(total)
