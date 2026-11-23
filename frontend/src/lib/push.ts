import { api } from "@/api/client"

/** Push needs a service worker, the Push API and notifications. On the iPhone only in the home screen app. */
export const pushSupported = () =>
  typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window

/** Opened from the home screen, not in Safari */
export const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true

export const isIos = () => /iPhone|iPad|iPod/.test(navigator.userAgent)

function keyBytes(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/")
  const raw = atob(padded)
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return bytes
}

function body(subscription: PushSubscription) {
  const json = subscription.toJSON()
  return JSON.stringify({ endpoint: json.endpoint, p256dh: json.keys?.p256dh, auth: json.keys?.auth })
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  const registration = await navigator.serviceWorker.ready
  return registration.pushManager.getSubscription()
}

/** Asks for permission (must run from a tap) and registers this device with the server */
export async function enablePush(publicKey: string): Promise<void> {
  const permission = await Notification.requestPermission()
  if (permission !== "granted") throw new Error("Mitteilungen wurden nicht erlaubt. Das lässt sich in den iOS-Einstellungen ändern.")
  const registration = await navigator.serviceWorker.ready
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) }))
  await api("/push/subscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: body(subscription) })
}

export async function disablePush(): Promise<void> {
  const subscription = await currentSubscription()
  if (!subscription) return
  await api("/push/unsubscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: body(subscription) })
  await subscription.unsubscribe()
}

export const testPush = () => api("/push/test", { method: "POST" })
