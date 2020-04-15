from digi import ble

def find_advertiser(substring):
    scanner = ble.gap_scan(100, interval_us=2500, window_us=2500)
    for adv in scanner:
        if substring in adv['payload']:
            return adv['address']
    return None
