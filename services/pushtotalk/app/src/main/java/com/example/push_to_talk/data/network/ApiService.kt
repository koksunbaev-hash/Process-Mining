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
 * РљРѕРЅС‚СЂР°РєС‚ backend-Р° (`backend/app/api/speech.py`).
 *
 * Р‘Р°Р·РѕРІС‹Р№ Р°РґСЂРµСЃ РїСЂРёС…РѕРґРёС‚ РёР· `BuildConfig.API_BASE_URL`, РїРѕСЌС‚РѕРјСѓ РїСѓС‚Рё Р·РґРµСЃСЊ
 * РІСЃРµРіРґР° РѕС‚РЅРѕСЃРёС‚РµР»СЊРЅС‹Рµ Рё РЅРµ СЃРѕРґРµСЂР¶Р°С‚ С…РѕСЃС‚Р°.
 */
interface ApiService {

    /**
     * РћС‚РїСЂР°РІР»СЏРµС‚ СЂР°СЃРїРѕР·РЅР°РЅРЅС‹Р№ С‚РµРєСЃС‚.
     *
     * РћС‚РІРµС‚ 4xx/5xx РїСЂРµРІСЂР°С‰Р°РµС‚СЃСЏ Retrofit-РѕРј РІ `HttpException`, РєРѕС‚РѕСЂС‹Р№
     * [NetworkErrorMapper] РїРµСЂРµРІРѕРґРёС‚ РІ С‚РёРїРёР·РёСЂРѕРІР°РЅРЅСѓСЋ РѕС€РёР±РєСѓ РґРѕРјРµРЅР°.
     */
    @POST("api/speech")
    suspend fun sendText(@Body request: SendTextDto): SendTextResponseDto

    @Multipart
    @POST("api/speech/transcribe")
    suspend fun transcribeAudio(@Part file: MultipartBody.Part): TranscriptionResponseDto
}
