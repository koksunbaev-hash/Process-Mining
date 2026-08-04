package com.example.push_to_talk.data.repository

import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.data.network.ApiService
import com.example.push_to_talk.fake.FakeLogger
import com.example.push_to_talk.fake.TestDispatcherProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Сквозная проверка против живого backend-а: боевой сетевой стек приложения
 * (Retrofit + DTO + [RetrofitNetworkRepository]) против настоящего сервера.
 *
 * По умолчанию тест пропускается, поэтому `./gradlew test` не требует запущенного
 * сервиса и не ломает CI. Чтобы прогнать его, укажите адрес:
 *
 *     ./gradlew testDebugUnitTest --tests '*RealBackendIntegrationTest*' \
 *         -PbackendUrl=http://192.168.0.168:8080/
 *
 * либо задайте переменную окружения `PTT_BACKEND_URL`.
 */
class RealBackendIntegrationTest {

    // Gradle всегда передаёт системное свойство, поэтому пустая строка означает
    // «адрес не задан» — иначе тест пытался бы стучаться в никуда.
    private val baseUrl: String? = sequenceOf(
        System.getProperty("ptt.backend.url"),
        System.getenv("PTT_BACKEND_URL"),
    ).firstOrNull { !it.isNullOrBlank() }

    private val json = Json { ignoreUnknownKeys = true }

    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()

    @Test
    fun `текст доходит до сервера и появляется в истории`() = runTest {
        assumeTrue("Адрес backend-а не задан — сквозной тест пропущен", baseUrl != null)
        val url = requireNotNull(baseUrl)

        val repository = RetrofitNetworkRepository(
            apiService = Retrofit.Builder()
                .baseUrl(url)
                .client(client)
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()
                .create(ApiService::class.java),
            dispatchers = TestDispatcherProvider(Dispatchers.IO),
            logger = FakeLogger(),
        )

        // Метка делает проверку устойчивой к чужим записям в общей базе.
        val marker = "Проверка связи ${System.nanoTime()}"

        val result = repository.sendText(marker)

        assertTrue("Сервер не принял текст: $result", result is AppResult.Success)
        assertTrue("Текст не появился в /api/messages", fetchMessages(url).contains(marker))
    }

    private fun fetchMessages(baseUrl: String): String {
        val request = Request.Builder().url("${baseUrl.trimEnd('/')}/api/messages").build()
        return client.newCall(request).execute().use { response ->
            response.body?.string().orEmpty()
        }
    }
}
