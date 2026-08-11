package com.example.push_to_talk.data.auth

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

data class KmsLoginResult(
    val success: Boolean,
    val cookies: List<String> = emptyList(),
)

class KmsAuthClient(baseUrl: String) {

    private val loginUrl = baseUrl.trimEnd('/') + "/login/"
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .followRedirects(false)
        .build()

    suspend fun login(username: String, password: String): Boolean =
        loginSession(username, password).success

    suspend fun loginSession(username: String, password: String): KmsLoginResult = withContext(Dispatchers.IO) {
        val loginPageRequest = Request.Builder()
            .url(loginUrl)
            .get()
            .build()

        client.newCall(loginPageRequest).execute().use { loginPageResponse ->
            if (!loginPageResponse.isSuccessful) return@withContext KmsLoginResult(false)

            val csrfToken = csrfFromCookie(loginPageResponse.headers("Set-Cookie"))
                ?: csrfFromHtml(loginPageResponse.body?.string().orEmpty())
                ?: return@withContext KmsLoginResult(false)

            val initialCookies = cookiePairs(loginPageResponse.headers("Set-Cookie"))
            val form = FormBody.Builder()
                .add("username", username)
                .add("password", password)
                .add("csrfmiddlewaretoken", csrfToken)
                .add("next", "")
                .build()

            val request = Request.Builder()
                .url(loginUrl)
                .post(form)
                .header("Cookie", initialCookies.joinToString("; "))
                .header("Referer", loginUrl)
                .build()

            client.newCall(request).execute().use { response ->
                val responseCookies = cookiePairs(response.headers("Set-Cookie"))
                val cookies = (initialCookies + responseCookies).distinctBy { it.substringBefore('=') }
                val success = response.code in 300..399 && cookies.any { it.startsWith("sessionid=") }
                KmsLoginResult(success = success, cookies = if (success) cookies else emptyList())
            }
        }
    }

    private fun cookiePairs(cookies: List<String>): List<String> =
        cookies.mapNotNull { cookie ->
            cookie.substringBefore(';')
                .trim()
                .takeIf { it.contains('=') }
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
