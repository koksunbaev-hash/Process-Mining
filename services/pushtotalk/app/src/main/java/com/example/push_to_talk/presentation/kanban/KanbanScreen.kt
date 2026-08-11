package com.example.push_to_talk.presentation.kanban

import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView

@Composable
fun KanbanScreen(
    kmsBaseUrl: String,
    kmsCookies: String,
    modifier: Modifier = Modifier,
) {
    val boardUrl = remember(kmsBaseUrl) { kmsBaseUrl.trimEnd('/') + "/bakery/board/" }

    AndroidView(
        modifier = modifier.fillMaxSize(),
        factory = { context ->
            val cookieManager = CookieManager.getInstance()
            cookieManager.setAcceptCookie(true)
            kmsCookies.lines()
                .filter { it.isNotBlank() }
                .forEach { cookieManager.setCookie(kmsBaseUrl, it) }
            cookieManager.flush()

            WebView(context).apply {
                webViewClient = WebViewClient()
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.loadWithOverviewMode = true
                settings.useWideViewPort = true
                loadUrl(boardUrl)
            }
        },
        update = { webView ->
            val cookieManager = CookieManager.getInstance()
            kmsCookies.lines()
                .filter { it.isNotBlank() }
                .forEach { cookieManager.setCookie(kmsBaseUrl, it) }
            cookieManager.flush()
            if (webView.url != boardUrl) {
                webView.loadUrl(boardUrl)
            }
        },
    )
}
