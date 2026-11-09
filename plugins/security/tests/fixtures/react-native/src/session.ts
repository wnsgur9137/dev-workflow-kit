import AsyncStorage from '@react-native-async-storage/async-storage'

export async function saveSession(token: string) {
  await AsyncStorage.setItem('authToken', token)
  await AsyncStorage.setItem('theme', 'dark')
  console.log('saved token', token)
  if (__DEV__) {
    console.log('dev token', token)
  }
}
