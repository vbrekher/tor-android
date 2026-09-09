from pathlib import Path
import sys

SERVICE = Path("tor-android-binary/src/main/java/org/torproject/jni/TorService.java")
TEST = Path("tor-android-binary/src/androidTest/java/org/torproject/jni/TorServiceTest.java")

TEST_METHOD = r'''
    @Test
    public void testShutdownStatusOrder() throws TimeoutException, InterruptedException {
        final CountDownLatch startedLatch = new CountDownLatch(1);
        final CountDownLatch stoppingLatch = new CountDownLatch(1);
        final CountDownLatch stoppedLatch = new CountDownLatch(1);
        final AtomicInteger shutdownSequence = new AtomicInteger();
        final AtomicInteger stoppingOrder = new AtomicInteger();
        final AtomicInteger stoppedOrder = new AtomicInteger();

        BroadcastReceiver receiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (!TorService.ACTION_STATUS.equals(intent.getAction())) {
                    return;
                }
                String status = intent.getStringExtra(TorService.EXTRA_STATUS);
                if (TorService.STATUS_ON.equals(status)) {
                    startedLatch.countDown();
                } else if (TorService.STATUS_STOPPING.equals(status)) {
                    stoppingOrder.compareAndSet(0, shutdownSequence.incrementAndGet());
                    stoppingLatch.countDown();
                } else if (TorService.STATUS_OFF.equals(status)) {
                    stoppedOrder.compareAndSet(0, shutdownSequence.incrementAndGet());
                    stoppedLatch.countDown();
                }
            }
        };

        HandlerThread handlerThread = new HandlerThread(receiver.getClass().getSimpleName());
        handlerThread.start();
        Handler handler = new Handler(handlerThread.getLooper());
        context.registerReceiver(
                receiver, new IntentFilter(TorService.ACTION_STATUS), null, handler);

        Intent serviceIntent = new Intent(context, TorService.class);
        IBinder binder = serviceRule.bindService(serviceIntent);
        torService = ((TorService.LocalBinder) binder).getService();
        assertTrue("Tor did not reach ON", startedLatch.await(120, TimeUnit.SECONDS));

        serviceRule.unbindService();
        assertTrue("STOPPING was not broadcast", stoppingLatch.await(30, TimeUnit.SECONDS));
        assertTrue("OFF was not broadcast", stoppedLatch.await(30, TimeUnit.SECONDS));
        assertTrue(
                "STOPPING must be broadcast before OFF",
                stoppingOrder.get() < stoppedOrder.get());

        context.unregisterReceiver(receiver);
        handlerThread.quitSafely();
    }

'''


def add_test():
    text = TEST.read_text()
    if "testShutdownStatusOrder" in text:
        return
    import_anchor = "import java.util.concurrent.TimeoutException;\n"
    if import_anchor not in text:
        raise SystemExit("test import anchor not found")
    text = text.replace(
        import_anchor,
        import_anchor + "import java.util.concurrent.atomic.AtomicInteger;\n",
        1,
    )
    method_anchor = "    @Test\n    public void testOverridingDefaultsTorrc()"
    if method_anchor not in text:
        raise SystemExit("test method anchor not found")
    text = text.replace(method_anchor, TEST_METHOD + method_anchor, 1)
    TEST.write_text(text)


def add_fix():
    text = SERVICE.read_text()
    old_finally = """            } finally {\n                broadcastStatus(context, STATUS_STOPPING);\n                mainConfigurationFree();\n                TorService.this.stopSelf();\n            }\n"""
    new_finally = """            } finally {\n                broadcastStoppingIfNeeded(context);\n                mainConfigurationFree();\n                TorService.this.stopSelf();\n            }\n"""
    if old_finally in text:
        text = text.replace(old_finally, new_finally, 1)
    elif new_finally not in text:
        raise SystemExit("tor thread finally anchor not found")

    old_destroy = """    public void onDestroy() {\n        super.onDestroy();\n        if (torControlConnection != null) {\n"""
    new_destroy = """    public void onDestroy() {\n        super.onDestroy();\n        broadcastStoppingIfNeeded(TorService.this);\n        if (torControlConnection != null) {\n"""
    if old_destroy in text:
        text = text.replace(old_destroy, new_destroy, 1)
    elif new_destroy not in text:
        raise SystemExit("onDestroy anchor not found")

    helper_anchor = """    /**\n     * Broadcasts the current status to any apps following the status of TorService.\n     */\n    private static void sendBroadcastStatusIntent(Context context) {\n"""
    helper = """    private static synchronized void broadcastStoppingIfNeeded(Context context) {\n        if (STATUS_STOPPING.equals(currentStatus) || STATUS_OFF.equals(currentStatus)) {\n            return;\n        }\n        broadcastStatus(context, STATUS_STOPPING);\n    }\n\n"""
    if "private static synchronized void broadcastStoppingIfNeeded" not in text:
        if helper_anchor not in text:
            raise SystemExit("status helper anchor not found")
        text = text.replace(helper_anchor, helper + helper_anchor, 1)

    old_broadcast = "private static void broadcastStatus(Context context, String currentStatus) {"
    new_broadcast = "private static synchronized void broadcastStatus(Context context, String currentStatus) {"
    if old_broadcast in text:
        text = text.replace(old_broadcast, new_broadcast, 1)
    elif new_broadcast not in text:
        raise SystemExit("broadcastStatus anchor not found")

    SERVICE.write_text(text)


if len(sys.argv) != 2 or sys.argv[1] not in {"test", "fix"}:
    raise SystemExit("usage: issue73_patch.py test|fix")

add_test()
if sys.argv[1] == "fix":
    add_fix()
