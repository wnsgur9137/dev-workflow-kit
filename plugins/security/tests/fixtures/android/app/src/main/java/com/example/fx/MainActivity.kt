package com.example.fx

import android.app.Activity
import android.os.Bundle
import android.webkit.WebView

class MainActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.allowFileAccess = true
        web.addJavascriptInterface(Bridge(), "bridge")
        web.loadUrl(intent.getStringExtra("url") ?: "https://example.com")
        setContentView(web)
    }
}

class Bridge
