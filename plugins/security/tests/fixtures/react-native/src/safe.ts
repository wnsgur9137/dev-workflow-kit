// 음성 사례 — 기준선 must_not_find (이 파일에서는 아무것도 잡히면 안 된다)
import AsyncStorage from '@react-native-async-storage/async-storage'

export async function savePrefs(lang: string, token: string, tokenizer: object) {
  await AsyncStorage.setItem('theme', 'dark')
  await AsyncStorage.setItem('tokenizer_lang', lang)
  console.log('Refresh token expired')
  console.log(tokenizer)
  await fetch('http://localhost:8081/status')
  if (__DEV__) {
    console.log('dev token', token)
  }
}
