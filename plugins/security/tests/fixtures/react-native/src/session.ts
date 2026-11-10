import AsyncStorage from '@react-native-async-storage/async-storage'

export async function saveSession(token: string) {
  await AsyncStorage.setItem('authToken', token)
  await AsyncStorage.setItem('password', 'fixture-password-hunter2')
  console.log('saved token', token)
}
