package com.example.push_to_talk.data.repository

import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.data.network.ApiService
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.fake.FakeLogger
import com.example.push_to_talk.fake.TestDispatcherProvider
import com.example.push_to_talk.fake.errorOrFail
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.Timeout
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Проверяет боевой сетевой репозиторий против настоящего HTTP-сервера:
 * реальная сериализация, реальные коды ответа, реальные сетевые сбои.
 */
class RetrofitNetworkRepositoryTest {

    /** Каждый тест должен уложиться в это время, иначе зависание видно сразу. */
    @get:Rule
    val timeout: Timeout = Timeout.seconds(30)

    private lateinit var server: MockWebServer
    private lateinit var repository: RetrofitNetworkRepository
    private var serverStopped = false

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        encodeDefaults = true
    }

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        repository = createRepository()
    }

    @After
    fun tearDown() {
        stopServer()
    }

    /** Останавливает сервер ровно один раз: повторный `shutdown` подвисает. */
    private fun stopServer() {
        if (!serverStopped) {
            serverStopped = true
            server.shutdown()
        }
    }

    private fun createRepository(timeoutMillis: Long = 5_000): RetrofitNetworkRepository {
        val client = OkHttpClient.Builder()
            .connectTimeout(timeoutMillis, TimeUnit.MILLISECONDS)
            .readTimeout(timeoutMillis, TimeUnit.MILLISECONDS)
            .writeTimeout(timeoutMillis, TimeUnit.MILLISECONDS)
            .build()

        val apiService = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(ApiService::class.java)

        return RetrofitNetworkRepository(
            apiService = apiService,
            // Запросы к MockWebServer — настоящий ввод-вывод, поэтому здесь нужен
            // реальный диспетчер, а не тестовый с виртуальным временем.
            dispatchers = TestDispatcherProvider(Dispatchers.IO),
            logger = FakeLogger(),
        )
    }

    @Test
    fun `HTTP 200 возвращает Success`() = runTest {
        server.enqueue(jsonResponse(200, """{"status":"ok","id":1}"""))

        val result = repository.sendText("hello")

        assertTrue(result is AppResult.Success)
    }

    @Test
    fun `запрос уходит на api-speech методом POST`() = runTest {
        server.enqueue(jsonResponse(200, """{"status":"ok","id":1}"""))

        repository.sendText("Привет сервер")

        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("/api/speech", recorded.path)
        assertEquals("""{"text":"Привет сервер"}""", recorded.body.readUtf8())
    }

    @Test
    fun `текст обрезается перед отправкой`() = runTest {
        server.enqueue(jsonResponse(200, """{"status":"ok","id":1}"""))

        repository.sendText("  привет  ")

        assertEquals("""{"text":"привет"}""", server.takeRequest().body.readUtf8())
    }

    @Test
    fun `ответ без поля id принимается`() = runTest {
        server.enqueue(jsonResponse(200, """{"status":"ok"}"""))

        assertTrue(repository.sendText("hello") is AppResult.Success)
    }

    @Test
    fun `неизвестные поля в ответе не ломают разбор`() = runTest {
        server.enqueue(jsonResponse(200, """{"status":"ok","id":1,"extra":"поле из будущего"}"""))

        assertTrue(repository.sendText("hello") is AppResult.Success)
    }

    @Test
    fun `HTTP 400 возвращает ошибку запроса`() = runTest {
        server.enqueue(jsonResponse(400, """{"status":"error","message":"empty text"}"""))

        val result = repository.sendText("hello")

        assertEquals(AppError.Network.Http(400), result.errorOrFail())
    }

    @Test
    fun `HTTP 422 возвращает ошибку запроса`() = runTest {
        server.enqueue(jsonResponse(422, """{"status":"error","message":"validation error"}"""))

        assertEquals(AppError.Network.Http(422), repository.sendText("hello").errorOrFail())
    }

    @Test
    fun `HTTP 500 возвращает ошибку сервера`() = runTest {
        server.enqueue(jsonResponse(500, """{"status":"error","message":"internal"}"""))

        assertEquals(AppError.Network.Server(500), repository.sendText("hello").errorOrFail())
    }

    @Test
    fun `HTTP 503 возвращает ошибку сервера`() = runTest {
        server.enqueue(jsonResponse(503, ""))

        assertEquals(AppError.Network.Server(503), repository.sendText("hello").errorOrFail())
    }

    @Test
    fun `таймаут ответа возвращает Timeout`() = runTest {
        repository = createRepository(timeoutMillis = 250)
        server.enqueue(
            jsonResponse(200, """{"status":"ok","id":1}""")
                // Задержка заметно больше таймаута клиента, но достаточно короткая,
                // чтобы `shutdown` в tearDown не ждал её долго.
                .setBodyDelay(2, TimeUnit.SECONDS),
        )

        assertEquals(AppError.Network.Timeout, repository.sendText("hello").errorOrFail())
    }

    @Test
    fun `обрыв соединения возвращает NoConnection`() = runTest {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))

        assertEquals(AppError.Network.NoConnection, repository.sendText("hello").errorOrFail())
    }

    @Test
    fun `выключенный сервер возвращает NoConnection`() = runTest {
        stopServer()

        val error = repository.sendText("hello").errorOrFail()

        assertEquals(AppError.Network.NoConnection, error)
    }

    @Test
    fun `некорректный JSON возвращает ошибку сериализации`() = runTest {
        server.enqueue(jsonResponse(200, """{"status": }"""))

        assertEquals(
            AppError.Network.Serialization,
            repository.sendText("hello").errorOrFail(),
        )
    }

    @Test
    fun `ответ без обязательного поля возвращает ошибку сериализации`() = runTest {
        server.enqueue(jsonResponse(200, """{"id":1}"""))

        assertEquals(
            AppError.Network.Serialization,
            repository.sendText("hello").errorOrFail(),
        )
    }

    @Test
    fun `пустой текст не доходит до сервера`() = runTest {
        val result = repository.sendText("   ")

        assertEquals(AppError.Validation.EmptyText, result.errorOrFail())
        assertEquals(0, server.requestCount)
    }

    private fun jsonResponse(code: Int, body: String): MockResponse = MockResponse()
        .setResponseCode(code)
        .setHeader("Content-Type", "application/json")
        .setBody(body)
}
