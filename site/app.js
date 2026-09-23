import { Keypair } from "https://esm.sh/@solana/web3.js@1.95.8?bundle";

const PLANET_FORGE_URL = "https://planet-forge.com";
let generatedKeypair = null;

const $ = (id) => document.getElementById(id);
const show = (element) => element.classList.remove("hidden");
const hide = (element) => element.classList.add("hidden");

function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.classList.add("show");
  window.setTimeout(() => element.classList.remove("show"), 2800);
}

function shortAddress(address) {
  return `${address.slice(0, 6)}…${address.slice(-6)}`;
}

function downloadBackup() {
  if (!generatedKeypair) return;
  const address = generatedKeypair.publicKey.toBase58();
  const secretKey = Array.from(generatedKeypair.secretKey);
  const payload = {
    format: "solana-keypair",
    network: "mainnet-beta",
    publicKey: address,
    secretKey,
    warning: "Keep this file offline and private. Anyone with it controls this wallet.",
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `planetforge-wallet-${address.slice(0, 8)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
  toast("Backup downloaded — store it offline");
}

async function copyAddress() {
  if (!generatedKeypair) return;
  await navigator.clipboard.writeText(generatedKeypair.publicKey.toBase58());
  toast("Public address copied");
}

function generateWallet() {
  generatedKeypair = Keypair.generate();
  $("generated-address").textContent = generatedKeypair.publicKey.toBase58();
  $("secret-key").textContent = Array.from(generatedKeypair.secretKey).join(", ");
  show($("generated-panel"));
  hide($("secret-panel"));
  toast("Wallet generated locally in this browser");
}

function providerFor(name) {
  if (name === "phantom") return window.phantom?.solana ?? (window.solana?.isPhantom ? window.solana : null);
  if (name === "solflare") return window.solflare ?? null;
  if (name === "backpack") return window.backpack?.solana ?? null;
  return null;
}

async function connectProvider(name) {
  const provider = providerFor(name);
  if (!provider) {
    const installUrls = {
      phantom: "https://phantom.app/",
      solflare: "https://solflare.com/",
      backpack: "https://backpack.app/",
    };
    toast(`${name[0].toUpperCase() + name.slice(1)} not detected — install it first`);
    window.open(installUrls[name], "_blank", "noopener,noreferrer");
    return;
  }
  try {
    const response = await provider.connect();
    const address = response.publicKey?.toString() ?? provider.publicKey?.toString();
    if (!address) throw new Error("Provider did not return a public address");
    $("connection-status").classList.add("connected");
    $("connection-status").lastElementChild.textContent = `${name.toUpperCase()} CONNECTED`;
    $("connected-address").textContent = shortAddress(address);
    show($("connected-address"));
    toast("Wallet connected — open PlanetForge to continue");
  } catch (error) {
    if (error?.code === 4001) toast("Connection request was rejected");
    else toast("Could not connect to that wallet");
  }
}

$("generate").addEventListener("click", generateWallet);
$("export-wallet").addEventListener("click", downloadBackup);
$("copy-address").addEventListener("click", copyAddress);
$("reveal-key").addEventListener("click", () => {
  if (!generatedKeypair) return;
  if ($("secret-panel").classList.contains("hidden")) {
    if (!window.confirm("Reveal the secret key? Anyone who sees it can control this mainnet wallet.")) return;
    show($("secret-panel"));
    $("reveal-key").textContent = "Hide secret key";
  } else {
    hide($("secret-panel"));
    $("reveal-key").textContent = "Show secret key";
  }
});
$("phantom").addEventListener("click", () => connectProvider("phantom"));
$("solflare").addEventListener("click", () => connectProvider("solflare"));
$("backpack").addEventListener("click", () => connectProvider("backpack"));
window.addEventListener("beforeunload", () => { generatedKeypair = null; });

// Keep this explicit: no private key is posted to PlanetForge or the bot.
console.info(`Forge Portal ready for ${PLANET_FORGE_URL}`);
