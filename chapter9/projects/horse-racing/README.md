# Derby Day

브라우저에서 즐기는 싱글 플레이어 경마 베팅 게임입니다. 실결제 없이 가상 크레딧만 사용합니다.

## 시작하기

```sh
npm install
npm run dev
```

## 검증

```sh
npm test
npm run build
npm run browser:setup   # 첫 브라우저 점검 전 Chromium 설치
npm run test:browser    # 로비 → 설정 → 경주 → 정산 → 저장/자동 복귀
```

브라우저 검증 화면은 `artifacts/` 아래 PNG로 저장됩니다. 게임 잔고, 전적, 사운드, 참가마 수는 `localStorage`에 저장됩니다.
