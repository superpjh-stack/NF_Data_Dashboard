# Hostinger VPS 배포

대상: `srv1934103` (`187.52.127.215`), 프로젝트 `/docker/nf-data-dashboard`.
Docker Compose 프로젝트 이름은 `nf-data-dashboard`이며 Hostinger Docker Manager에서 같은 이름으로 확인한다.

## 접속 구조

- 외부 URL: `https://srv1934103.hstgr.cloud:8770/`
- TLS 게이트웨이: `nf-data-dashboard-gateway` (nginx), 호스트 포트 8770 → HTTPS 443.
- 대시보드: `nf-data-dashboard-app`, 내부 네트워크의 포트 8770만 사용.
- 로그인은 대시보드·API·보고서·CSV·원본 다운로드·정적 자원 전체에 적용한다. `/healthz`만 상태 확인용으로 공개한다.
- 인증 자격이 비어 있으면 컨테이너가 정상 서비스로 열리지 않는다. Compose에서도 사용자·비밀번호 필수값을 검사한다.
- 앱은 비루트 사용자(UID 10001), 읽기 전용 루트 파일시스템, 권한 상승 금지로 실행한다. 데이터·보고서·원본도 읽기 전용 마운트한다.
- `SOURCE_ROOT=/sources`로 원본 위치를 바꾸므로 Mac 절대 경로를 컨테이너에 그대로 만들지 않는다. 파일의 상대 경로와 해시는 유지한다.

## 배포

로컬 원본·분석 DB·EDA 보고서가 준비되고 `~/.ssh/hostinger`로 VPS에 접속할 수 있는 상태에서 실행한다.

```sh
./Deploy_VPS.command
```

1. 로컬 SQLite 무결성·EDA 버전·원본 파일 해시를 확인한다.
2. VPS의 새 `releases/<UTC 시각>/` 폴더에 코드·DB·보고서·원본을 전송한다.
3. VPS에서 다시 원본 1,877개(현재 스냅샷 기준)의 해시, DB 해시·무결성과 테이블 행 수를 대조한다.
4. 해당 릴리스 태그의 이미지로 빌드하고 새 읽기 전용 컨테이너를 시작한다.
5. 인증 없는 접근의 401, 인증 후 페이지·API·Summary·EDA·CSV·보고서, 원본 해시·셀 미리보기, 공개 HTTPS 인증서를 검증한다.
6. 성공 후 `.env`의 활성 릴리스를 확정하고 배포 검증 결과를 저장한다. 이전 배포가 있고 공개 검증에 실패하면 이전 환경·Compose 설정·이미지 태그로 돌아간다.

비밀번호는 VPS의 `/docker/nf-data-dashboard/.env`와 로컬 `.deployment/access.txt`(권한 600)에만 보관한다. 저장소와 Docker 빌드 컨텍스트에는 포함하지 않는다. 로컬 검증 결과는 `.deployment/verification.json`, 원격 결과는 `/docker/nf-data-dashboard/deployment.json`에 저장한다.

원본 새로고침은 로컬에서 `Refresh_Data.command`로 실행한 뒤 재배포한다. 서버에서 OCR·원본 수정·검수 저장·모델 학습을 실행하지 않는다.

## TLS 인증서 갱신

기존 Caddy가 관리하는 `srv1934103.hstgr.cloud` 인증서 디렉터리만 게이트웨이에 읽기 전용 마운트한다. 기존 서비스의 라우팅과 인증서 발급 구성을 변경하지 않는다.

`/etc/cron.d/nf-data-dashboard-tls`는 30분마다 인증서·키의 해시 변경을 확인한다. 변경되었을 때만 니즈푸드 게이트웨이 설정을 검사하고 nginx를 reload한다. 인증서 개인키·비밀번호는 로그에 출력하지 않는다.

## 상태 확인

VPS에서:

```sh
cd /docker/nf-data-dashboard
docker compose ps
docker compose logs --tail 50 app gateway
```

이미지 태그와 마운트 경로는 `.env`의 `APP_VERSION`, `RELEASE_DIR`로 고정한다. 기존 릴리스는 자동 삭제하지 않는다.
