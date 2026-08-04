package com.example.push_to_talk.data.network

import javax.inject.Inject
import javax.inject.Singleton

/**
 * Источник токена для заголовка `Authorization`.
 *
 * В MVP авторизации нет: сервис работает только в локальной сети, а никакие
 * учётные данные в приложении не хранятся. Точка расширения оставлена намеренно —
 * когда появится аутентификация, достаточно подменить реализацию в Hilt-модуле,
 * не трогая [ApiService], репозитории и UI.
 */
interface AuthTokenProvider {

    /** Токен без префикса `Bearer`, либо `null`, если запрос идёт анонимно. */
    fun token(): String?
}

/** Реализация по умолчанию: запросы уходят без авторизации. */
@Singleton
class NoAuthTokenProvider @Inject constructor() : AuthTokenProvider {
    override fun token(): String? = null
}
