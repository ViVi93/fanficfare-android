package com.vivi.aharana

import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.atomic.AtomicInteger

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
 *
 * Two lanes: user-initiated work (share/download, update, force download, the
 * Book Detail buttons and refresh-all) is *visible* and takes priority. Background
 * metadata lookups are not shown in the download queue, so without a priority rule
 * a listing page's worth of hidden metadata fetches could sit in front of a
 * download the user just shared and make it look stuck at "waiting".
 */
object FanFicFareGate {

    private val mutex = Mutex()

    /** Minimum spacing between two consecutive engine calls. */
    private const val MIN_GAP_MS = 1_000L

    /** How often a background call re-checks whether visible work is waiting. */
    private const val BACKGROUND_POLL_MS = 200L

    @Volatile
    private var lastFinishedAt = 0L

    /** Visible (user-initiated) calls that are queued for the engine right now. */
    private val visibleWaiting = AtomicInteger(0)

    suspend fun <T> run(block: suspend () -> T): T = run(visible = true, block = block)

    /**
     * @param visible true for user-initiated work, false for background metadata.
     *   Background work waits until nothing visible is queued before taking the
     *   engine, so hidden lookups can never delay a download the user asked for.
     *   It may still wait for a visible call that is already running (and a visible
     *   call may wait for a background one already in flight) - the gate is
     *   one-call-at-a-time, not preemptive.
     */
    suspend fun <T> run(visible: Boolean, block: suspend () -> T): T {
        if (visible) visibleWaiting.incrementAndGet()
        try {
            if (!visible) {
                // Do not even queue for the engine while the user's work is waiting.
                while (visibleWaiting.get() > 0) {
                    delay(BACKGROUND_POLL_MS)
                }
            }
            return mutex.withLock {
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
        } finally {
            if (visible) visibleWaiting.decrementAndGet()
        }
    }

    /**
     * Blocking variant of [run] for callers that are not coroutines: the activity
     * `Thread { }` paths (Book Detail update / force-download and the library
     * refresh-all loop). Those used to call the engine directly, so they still ran
     * alongside - and burst the same host as - whatever the WorkManager queue was
     * doing. They now take the same single-file gate, in the visible lane.
     */
    fun <T> runBlocking(block: () -> T): T = kotlinx.coroutines.runBlocking { run(visible = true, block = block) }
}
