#!/usr/bin/env python3
"""
Sweety appcast.xml 유효성 검사 스크립트

검사 항목:
  1. XML 구조 및 필수 속성 존재 여부
  2. 버전/빌드 번호 고유성
  3. 빌드 번호 내림차순 정렬 여부
  4. URL 형식 및 버전 일치 여부
  5. Ed25519 서명 형식 (64바이트 base64)
  6. 파일 크기 (최소 1MB)
  7. minimumSystemVersion 일관성
"""

import base64
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

SPARKLE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
APPCAST_FILE = "appcast.xml"
MIN_DMG_SIZE = 1_000_000  # 1MB

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


# --- XML 파싱 ---
try:
    tree = ET.parse(APPCAST_FILE)
except ET.ParseError as e:
    print(f"[FAIL] XML 파싱 오류: {e}")
    sys.exit(1)

root = tree.getroot()
if root.tag != "rss":
    err("루트 태그가 <rss>가 아님")

channel = root.find("channel")
if channel is None:
    print("[FAIL] <channel> 요소 없음")
    sys.exit(1)

items = channel.findall("item")
if not items:
    print("[FAIL] <item> 요소 없음")
    sys.exit(1)

print(f"총 {len(items)}개 항목 검사 중...\n")

# --- 각 항목 검사 ---
short_versions = []
build_numbers = []
min_sys_versions = []

for idx, item in enumerate(items):
    enc = item.find("enclosure")
    title = item.findtext("title", f"항목#{idx+1}")

    # 필수 요소 확인
    if enc is None:
        err(f"{title}: <enclosure> 요소 없음")
        continue

    short = enc.get(f"{{{SPARKLE}}}shortVersionString")
    build_str = enc.get(f"{{{SPARKLE}}}version")
    url = enc.get("url")
    sig = enc.get(f"{{{SPARKLE}}}edSignature")
    length_str = enc.get("length")
    mime = enc.get("type")
    min_sys = enc.get(f"{{{SPARKLE}}}minimumSystemVersion")
    pub_date = item.findtext("pubDate")

    required = {
        "sparkle:shortVersionString": short,
        "sparkle:version": build_str,
        "url": url,
        "sparkle:edSignature": sig,
        "length": length_str,
        "type": mime,
    }
    for attr, val in required.items():
        if not val:
            err(f"{title}: 필수 속성 누락 — {attr}")

    if not all(required.values()):
        continue

    # 빌드 번호 정수 변환
    try:
        build = int(build_str)
    except ValueError:
        err(f"{title}: sparkle:version이 정수가 아님 ({build_str!r})")
        continue

    # URL 형식 검사: .../v{short}/Sweety-{short}.dmg
    expected_url_suffix = f"v{short}/Sweety-{short}.dmg"
    if expected_url_suffix not in url:
        err(f"{title}: URL이 버전과 불일치\n  URL: {url}\n  기대: ...{expected_url_suffix}")

    # URL이 GitHub releases를 가리키는지
    if "github.com" not in url:
        warn(f"{title}: URL이 GitHub을 가리키지 않음 ({url})")

    # 서명 형식 검사 (Ed25519 = 64바이트 = base64 88자)
    try:
        sig_bytes = base64.b64decode(sig)
        if len(sig_bytes) != 64:
            err(f"{title}: 서명 길이 오류 ({len(sig_bytes)}바이트, 64바이트여야 함)")
    except Exception:
        err(f"{title}: 서명이 유효한 base64가 아님")

    # 파일 크기 검사
    try:
        length = int(length_str)
        if length < MIN_DMG_SIZE:
            err(f"{title}: DMG 파일 크기가 너무 작음 ({length:,} bytes, 최소 {MIN_DMG_SIZE:,} bytes)")
    except ValueError:
        err(f"{title}: length가 정수가 아님 ({length_str!r})")

    # MIME 타입 검사
    if mime != "application/octet-stream":
        warn(f"{title}: 예상치 못한 MIME 타입 ({mime})")

    # pubDate 형식 검사
    if pub_date:
        try:
            parsedate_to_datetime(pub_date)
        except Exception:
            err(f"{title}: pubDate 형식 오류 ({pub_date!r})")
    else:
        warn(f"{title}: pubDate 없음")

    short_versions.append((short, title))
    build_numbers.append((build, title))
    if min_sys:
        min_sys_versions.append((min_sys, title))

# --- 전체 목록 레벨 검사 ---

# 고유성 검사
seen_short = {}
for sv, title in short_versions:
    if sv in seen_short:
        err(f"중복 shortVersionString: {sv} ({title} 및 {seen_short[sv]})")
    seen_short[sv] = title

seen_build = {}
for bn, title in build_numbers:
    if bn in seen_build:
        err(f"중복 빌드 번호: {bn} ({title} 및 {seen_build[bn]})")
    seen_build[bn] = title

# 빌드 번호 내림차순 정렬 검사
builds_only = [b for b, _ in build_numbers]
for i in range(len(builds_only) - 1):
    if builds_only[i] < builds_only[i + 1]:
        err(
            f"순서 오류: 빌드 {builds_only[i]} ({build_numbers[i][1]})가 "
            f"빌드 {builds_only[i+1]} ({build_numbers[i+1][1]}) 앞에 위치 (내림차순이어야 함)"
        )

# minimumSystemVersion 일관성 (경고만)
sys_ver_set = set(sv for sv, _ in min_sys_versions)
if len(sys_ver_set) > 1:
    warn(f"minimumSystemVersion 값이 통일되지 않음: {sorted(sys_ver_set)}")

# --- 결과 출력 ---
print("=" * 60)

if warnings:
    print(f"경고 {len(warnings)}개:")
    for w in warnings:
        print(f"  [WARN] {w}")
    print()

if errors:
    print(f"오류 {len(errors)}개:")
    for e in errors:
        print(f"  [FAIL] {e}")
    print()
    print(f"검사 실패: {len(errors)}개 오류 발견")
    sys.exit(1)
else:
    print(f"검사 통과: {len(items)}개 항목 모두 유효 (경고 {len(warnings)}개)")
