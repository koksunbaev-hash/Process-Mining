package com.example.push_to_talk.data.auth

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

class KmsAuthClient(baseUrl: String) {

    private val loginUrl = baseUrl.trimEnd('/') + "/login/"
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .followRedirects(false)
        .build()

    suspend fun login(username: String, password: String): Boolean = withContext(Dispatchers.IO) {
        val loginPageRequest = Request.Builder()
            .url(loginUrl)
            .get()
            .build()

        client.newCall(loginPageRequest).execute().use { loginPageResponse ->
            if (!loginPageResponse.isSuccessful) return@withContext false

            val csrfToken = csrfFromCookie(loginPageResponse.headers("Set-Cookie"))
                ?: csrfFromHtml(loginPageResponse.body?.string().orEmpty())
                ?: return@withContext false

            val cookieHeader = loginPageResponse.headers("Set-Cookie")
                .joinToString("; ") { it.substringBefore(';') }

            val form = FormBody.Builder()
                .add("username", username)
                .add("password", password)
                .add("csrfmiddlewaretoken", csrfToken)
                .add("next", "")
                .build()

            val request = Request.Builder()
                .url(loginUrl)
                .post(form)
                .header("Cookie", cookieHeader)
                .header("Referer", loginUrl)
                .build()

            client.newCall(request).execute().use { response ->
                val cookies = response.headers("Set-Cookie").joinToString("; ")
                response.code in 300..399 && cookies.contains("sessionid=")
            }
        }
    }

    private fun csrfFromCookie(cookies: List<String>): String? =
        cookies.asSequence()
            .mapNotNull { cookie ->
                cookie.split(';')
                    .firstOrNull { it.trim().startsWith("csrftoken=") }
                    ?.trim()
                    ?.substringAfter("csrftoken=")
            }
            .firstOrNull { it.isNotBlank() }

    private fun csrfFromHtml(html: String): String? {
        val marker = "name=\"csrfmiddlewaretoken\" value=\""
        val start = html.indexOf(marker)
        if (start < 0) return null
        return html.substring(start + marker.length)
            .substringBefore('"')
            .takeIf { it.isNotBlank() }
    }
}
