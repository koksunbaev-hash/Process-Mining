package com.example.push_to_talk.di

import com.example.push_to_talk.BuildConfig
import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.data.network.ApiService
import com.example.push_to_talk.data.network.AuthInterceptor
import com.example.push_to_talk.data.network.AuthTokenProvider
import com.example.push_to_talk.data.network.NoAuthTokenProvider
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    private const val CONNECT_TIMEOUT_SECONDS = 10L
    private const val READ_TIMEOUT_SECONDS = 120L
    private const val WRITE_TIMEOUT_SECONDS = 120L

    /**
     * Верхняя граница на весь вызов, включая переподключения. Без неё зависший
     * сервер держал бы индикатор отправки в UI дольше, чем read timeout.
     */
    private const val CALL_TIMEOUT_SECONDS = 180L

    private const val CONTENT_TYPE = "application/json"
    private const val TAG = "Network"
    private const val HEADER_AUTHORIZATION = "Authorization"

    @Provides
    @Singleton
    fun provideJson(): Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        encodeDefaults = true
    }

    @Provides
    @Singleton
    fun provideLoggingInterceptor(logger: Logger): HttpLoggingInterceptor =
        HttpLoggingInterceptor { message -> logger.d(TAG, message) }.apply {
            level = if (BuildConfig.NETWORK_LOGGING) {
                HttpLoggingInterceptor.Level.BODY
            } else {
                HttpLoggingInterceptor.Level.NONE
            }
            // Токен не должен попадать в logcat даже в debug-сборке.
            redactHeader(HEADER_AUTHORIZATION)
        }

    /** Общие заголовки запросов; сюда же добавляется авторизация, когда появится backend. */
    @Provides
    @Singleton
    fun provideHeaderInterceptor(): Interceptor = Interceptor { chain ->
        val request = chain.request().newBuilder()
            .header("Accept", CONTENT_TYPE)
            .header("X-Client", "android-push-to-talk/${BuildConfig.VERSION_NAME}")
            .build()
        chain.proceed(request)
    }

    @Provides
    @Singleton
    fun provideOkHttpClient(
        headerInterceptor: Interceptor,
        authInterceptor: AuthInterceptor,
        loggingInterceptor: HttpLoggingInterceptor,
    ): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(CONNECT_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .readTimeout(READ_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .writeTimeout(WRITE_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .callTimeout(CALL_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .addInterceptor(headerInterceptor)
        .addInterceptor(authInterceptor)
        // Логирование идёт последним, чтобы в лог попал уже итоговый запрос.
        .addInterceptor(loggingInterceptor)
        .build()

    @Provides
    @Singleton
    fun provideRetrofit(client: OkHttpClient, json: Json): Retrofit = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(client)
        .addConverterFactory(json.asConverterFactory(CONTENT_TYPE.toMediaType()))
        .build()

    @Provides
    @Singleton
    fun provideApiService(retrofit: Retrofit): ApiService = retrofit.create(ApiService::class.java)
}

/**
 * Привязки сетевых абстракций. Подключение реальной авторизации сводится
 * к замене реализации [AuthTokenProvider] здесь.
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class NetworkBindingsModule {

    @Binds
    @Singleton
    abstract fun bindAuthTokenProvider(impl: NoAuthTokenProvider): AuthTokenProvider
}
