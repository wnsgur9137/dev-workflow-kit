const TOKEN_KEY = 'k'

export async function save(token: string, authToken: string, userPassword: string, user: any) {
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
}
