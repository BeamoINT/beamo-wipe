#!/usr/bin/env python3
"""Validate classic USB pcap structure and summarize capture completeness."""
import argparse
import hashlib
import json
import struct


def summarize(path):
    with open(path, 'rb') as stream:
        header = stream.read(24)
        if len(header) != 24:
            raise ValueError('Truncated pcap header')
        magic = header[:4]
        if magic == b'\xd4\xc3\xb2\xa1':
            order = '<'
        elif magic == b'\xa1\xb2\xc3\xd4':
            order = '>'
        else:
            raise ValueError('Expected classic microsecond pcap')
        major, minor, _, _, snaplen, linktype = struct.unpack(order+'HHIIII', header[4:])
        if (major, minor) != (2, 4) or linktype not in (189, 220):
            raise ValueError('Expected Linux USB or USB mmap capture')
        packets = payload_bytes = truncated_packets = 0
        h = hashlib.sha256(header)
        while record := stream.read(16):
            if len(record) != 16:
                raise ValueError('Truncated packet header')
            _, _, size, original = struct.unpack(order+'IIII', record)
            if size > min(snaplen, 16*1024**2) or size > original:
                raise ValueError('Invalid capture length')
            data = stream.read(size)
            if len(data) != size:
                raise ValueError('Truncated packet payload')
            h.update(record)
            h.update(data)
            packets += 1
            payload_bytes += size
            truncated_packets += size < original
        if not packets:
            raise ValueError('Empty USB capture')
        return {'sha256': h.hexdigest(), 'packets': packets, 'payload_bytes': payload_bytes, 'snaplen_truncated_packets': truncated_packets, 'linktype': linktype}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+')
    args = parser.parse_args()
    print(json.dumps({p: summarize(p) for p in args.paths}, indent=2))


if __name__ == '__main__':
    main()
