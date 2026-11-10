const TOKEN_KEY = 'k'
const prefix = 'app'

export async function save(token: string, authToken: string, userPassword: string, password: string, user: any, x: boolean, hasToken: boolean, showPassword: boolean) {
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
}
