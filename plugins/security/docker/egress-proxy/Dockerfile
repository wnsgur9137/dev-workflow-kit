# egress-proxy — /security:scan-web 의 허용목록 이그레스 프록시 (tinyproxy, Q4)
#
# update.sh --images 가 로컬에서 빌드한다 (이슈 #35). 스캔 스크립트는 빌드하지 않고, 기록한 이미지 ID 로만 실행한다.
#   BASE: images.lock 의 egress-proxy-base(공식 alpine, digest 고정)를 update.sh 가 <image>@<digest> 로 넘긴다
#   tinyproxy: Alpine 저장소의 패키지 — apk 가 베이스 이미지의 Alpine 서명 키로 서명을 확인한다.
#     버전은 리비전(-rN)까지 고정한다. Alpine 은 같은 브랜치에 최신 리비전만 남기므로, 저장소에서 바뀌면 빌드가 실패한다
#     → 관리자가 PR 로 이 줄을 올린다 (docs/security/03 워크플로/업데이트 절차.md)
#
# 실행 설정은 이미지에 넣지 않는다 — compose-web.yml 이 설정·필터를 tmpfs(/run/dwk, uid 57981)에 쓰고 tinyproxy -d -c 로 실행한다.
# 쓰는 것: /usr/bin/tinyproxy, /bin/sh(설정 쓰기), nc(busybox, healthcheck)
ARG BASE
FROM ${BASE}
ARG TINYPROXY_VERSION=1.11.3-r0
RUN apk add --no-cache "tinyproxy=${TINYPROXY_VERSION}" \
 && addgroup -S -g 57981 dwk \
 && adduser -S -D -H -u 57981 -G dwk -s /sbin/nologin dwk \
 && rm -f /etc/tinyproxy/tinyproxy.conf
USER 57981:57981
ENTRYPOINT []
CMD ["/usr/bin/tinyproxy", "-v"]
