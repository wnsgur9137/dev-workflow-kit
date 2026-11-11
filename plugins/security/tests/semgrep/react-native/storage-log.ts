const TOKEN_KEY = 'k'
const prefix = 'app'

export async function save(token: string, authToken: string, userPassword: string, password: string, user: any, x: boolean, hasToken: boolean, showPassword: boolean, verbose: boolean, someFlag: boolean, p: string, hasher: any) {
  // ruleid: insecure-storage
  await AsyncStorage.setItem('authToken', token)
  // ruleid: insecure-storage
  await AsyncStorage.setItem(TOKEN_KEY, token)
  // ruleid: insecure-storage
  await AsyncStorage.setItem(kTokenKey, token)
  // ruleid: insecure-storage
  await AsyncStorage.setItem(`@app:refreshToken`, token)
  // ok: insecure-storage
  await AsyncStorage.setItem('tokenizer_lang', 'ko')
  // ok: insecure-storage
  await AsyncStorage.setItem('theme', 'dark')
  // ruleid: insecure-storage
  await AsyncStorage.setItem('TOKEN_KEY', token)
  // ruleid: insecure-storage
  await AsyncStorage.setItem('session_id', token)
  // ruleid: insecure-storage
  await AsyncStorage.setItem(`${prefix}:token`, token)
  // ruleid: insecure-storage
  await AsyncStorage.setItem('${prefix}_token', token)
  // ok: insecure-storage
  await AsyncStorage.setItem('tokenCount', '1')
  // ok: insecure-storage
  await AsyncStorage.setItem('PASSWORDLESS_ENABLED', '1')
  // ok: insecure-storage
  await AsyncStorage.setItem('last_token_refresh_at', '1')
  // 3차 리뷰 S5 — 버전 꼬리·복수 id
  // ruleid: insecure-storage
  await AsyncStorage.setItem('access_token_v2', token)
  // ruleid: insecure-storage
  await AsyncStorage.setItem('TOKEN_KEY_V2', token)
  // ruleid: insecure-storage
  await AsyncStorage.setItem('token_ids', token)
  // ok: insecure-storage
  await AsyncStorage.setItem('token_version', '2')

  // ruleid: sensitive-log
  console.log('saved', token)
  // ruleid: sensitive-log
  console.log(authToken)
  // ruleid: sensitive-log
  console.warn(userPassword)
  // ruleid: sensitive-log
  console.error(user.accessToken)
  // ruleid: sensitive-log
  console.log(`token=${token}`)
  // ruleid: sensitive-log
  console.log({ token })
  // ok: sensitive-log
  console.log('Refresh token expired')
  // ok: sensitive-log
  console.log(tokenizer, user.tokenCount)
  if (__DEV__) {
    // ok: sensitive-log
    console.log('dev', token)
  } else {
    // ruleid: sensitive-log
    console.log('release', token)
  }
  // ok: sensitive-log
  if (__DEV__) console.log('single', token)
  if (!__DEV__) {
    // ruleid: sensitive-log
    console.log('not dev', token)
  }

  // N1 — 인자가 식이어도 안의 식별자·멤버·키 이름을 본다 (구 규칙이 잡던 9줄)
  // ruleid: sensitive-log
  console.log('token: ' + token)
  // ruleid: sensitive-log
  console.log({ accessToken: user.at })
  // ruleid: sensitive-log
  console.log(JSON.stringify(token))
  // ruleid: sensitive-log
  console.log('pw', password.trim())
  // ruleid: sensitive-log
  console.log('user', user.token ?? '')
  // ruleid: sensitive-log
  console.log(token!)
  // ruleid: sensitive-log
  console.log('t', token as string)
  // ruleid: sensitive-log
  console.log(user['token'])
  // ruleid: sensitive-log
  console.log(`Bearer ${user.auth.accessToken}`)
  // ok: sensitive-log
  console.log('token: expired, please log in again')
  // ok: sensitive-log
  console.log(user['tokenizer'], 'password reset')
  // N8 — 불리언 이름·__DEV__ && 단락 평가·!__DEV__ 의 else·__DEV__ && 조건은 개발 분기
  // ok: sensitive-log
  console.log(hasToken, showPassword)
  // ok: sensitive-log
  __DEV__ && console.log(token)
  if (!__DEV__) {
    // ruleid: sensitive-log
    console.log('release', token)
  } else {
    // ok: sensitive-log
    console.log('dev', token)
  }
  if (__DEV__ && x) {
    // ok: sensitive-log
    console.log('dev', token)
  } else {
    // ruleid: sensitive-log
    console.log('release', token)
  }
  // 3차 리뷰 S4 — 호출·생성 대상 이름, 값이 리터럴인 객체 키, 뒤에 오는 __DEV__ 는 제외
  // ok: sensitive-log
  console.log('x', validatePassword(p))
  // ok: sensitive-log
  console.log('x', new Token())
  // ok: sensitive-log
  console.log('form', { password: '***' })
  // ruleid: sensitive-log
  console.log('x', hasher(token))
  // ruleid: sensitive-log
  console.log('form', { password: p })
  // ruleid: sensitive-log
  console.log('x', validatePassword(password))
  if (verbose && __DEV__) {
    // ok: sensitive-log
    console.log(token)
  }
  // ok: sensitive-log
  someFlag && __DEV__ && console.log(token)
  // 4차 리뷰 N2 — 뒤에 오는 __DEV__ 의 else·else if 쪽은 릴리스 빌드에서 실행된다
  if (x && __DEV__) { a() } else {
    // ruleid: sensitive-log
    console.log(token)
  }
  if (verbose && __DEV__) {
    a()
  } else if (x) {
    // ruleid: sensitive-log
    console.log('release', token)
  }
  // ruleid: sensitive-log
  if (x && __DEV__) a(); else console.log(token)
}
