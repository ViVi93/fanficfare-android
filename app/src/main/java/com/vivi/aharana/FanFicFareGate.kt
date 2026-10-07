package com.vivi.aharana

import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Process-wide serialization gate for FanFicFare engine calls.
 *
 * Why this exists: sharing several story URLs in quick succession enqueues one
 * WorkManager job per URL, and WorkManager runs those jobs concurrently
 * (`CoroutineWorker` executes `doWork` on the default dispatcher). Each job opens
 * its own Python/requests session, so the app fired N simultaneous requests at the
 * same host. Sites with anti-scraping limits - storiesonline.net in particular -
 * answer such a burst with HTTP 503 for every request in it, so all jobs failed
 * together and only succeeded when the user retried them one at a time.
 *
 * Every bridge call in [FanFicFareWorker] now runs inside [run], so exactly one
 * FanFicFare request is in flight at any moment and consecutive jobs are spaced by
 * at least [MIN_GAP_MS]. Waiting is cancellable (WorkManager cancellation releases
 * the coroutine), so cancelling a queued job never blocks the queue.
 */
object FanFicFareGate {

    private val mutex = Mutex()

    /** Minimum spacing between two consecutive engine calls. */
    private const val MIN_GAP_MS = 2_000L

    @Volatile
    private var lastFinishedAt = 0L

    suspend fun <T> run(block: suspend () -> T): T = mutex.withLock {
        val sinceLast = System.currentTimeMillis() - lastFinishedAt
        if (lastFinishedAt > 0L && sinceLast < MIN_GAP_MS) {
            delay(MIN_GAP_MS - sinceLast)
        }
        try {
            block()
        } finally {
            lastFinishedAt = System.currentTimeMillis()
        }
    }
}
