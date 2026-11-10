import React from 'react'
import { WebView } from 'react-native-webview'

// ruleid: webview-origin-wildcard
export const a = <WebView source={{ uri: 'https://example.com' }} originWhitelist={['*']} />
// ruleid: webview-origin-wildcard
export const b = <WebView originWhitelist={['*', 'about:blank']} javaScriptEnabled />
// ok: webview-origin-wildcard
export const c = <WebView originWhitelist={['https://*']} />
