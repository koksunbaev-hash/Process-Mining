package com.example.push_to_talk.data.network

import com.example.push_to_talk.data.network.dto.SendTextDto
import com.example.push_to_talk.data.network.dto.SendTextResponseDto
import com.example.push_to_talk.data.network.dto.TranscriptionResponseDto
import okhttp3.MultipartBody
import retrofit2.http.Body
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part

/**
 * Контракт backend-а (`backend/app/api/speech.py`).
 *
 * Базовый адрес приходит из `BuildConfig.API_BASE_URL`, поэтому пути здесь
 * всегда относительные и не содержат хоста.
 */
interface ApiService {

    /**
     * Отправляет распознанный текст.
     *
     * Ответ 4xx/5xx превращается Retrofit-ом в `HttpException`, который
     * [NetworkErrorMapper] переводит в типизированную ошибку домена.
     */
    @POST("api/speech")
    suspend fun sendText(@Body request: SendTextDto): SendTextResponseDto

    @Multipart
    @POST("api/speech/transcribe")
    suspend fun transcribeAudio(@Part file: MultipartBody.Part): TranscriptionResponseDto
}
