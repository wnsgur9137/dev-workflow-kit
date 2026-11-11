import React from 'react'
import { WebView } from 'react-native-webview'

export function Browser({ url }: { url: string }) {
  return <WebView source={{ uri: url }} originWhitelist={['*']} javaScriptEnabled />
}
