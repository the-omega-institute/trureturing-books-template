<!--
  Verification badge. Colour carries meaning (theme/tokens.json semantics):
    gid="<GID>"        green LEAN ✓ (links to the Lean source at the pinned commit) only when
                       trureturing.lock.json resolves the GID to a Lean theorem; a locked definition (or
                       other non-theorem) gets the neutral cyan LEAN DEF, an unlocked GID a red UNVERIFIED
    kind="definition"  always the neutral LEAN DEF (a definition is not a claim to verify)
    status="open"      red OPEN: an open problem, no Lean proof
    status="argued"    violet ARGUED: argued, but not kernel-verified
    status="written-proof" violet WRITTEN PROOF: a source proof, no matching Lean declaration; no gid
  ./tbook check and tools/node/slides-check.mjs reject unlocked GIDs, and non-theorem GIDs unless
  kind="definition", so UNVERIFIED should never ship.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { leanInfo, leanState } from '../lean'
import { t } from '../i18n'

const props = defineProps<{ gid?: string, status?: 'open' | 'argued' | 'written-proof', kind?: string }>()
const info = computed(() => leanInfo(props.gid))
const state = computed(() => leanState(info.value, props.status, props.kind))
const label = computed(() => ({
  'written-proof': t('badge.written_proof'),
  lean: t('badge.lean'),
  defined: t('slides.badge_defined'),
  open: t('badge.open'),
  argued: t('slides.badge_argued'),
  unverified: t('slides.badge_unverified'),
})[state.value])
const title = computed(() => ({
  'written-proof': t('badge.written_proof_title'),
  lean: `${t('badge.lean_title')} · ${info.value.name}`,
  defined: `${t('slides.badge_defined_title')} · ${info.value.name}`,
  open: t('badge.open_title'),
  argued: t('slides.badge_argued_title'),
  unverified: `${t('slides.badge_unverified_title')} · ${info.value.gid || '—'}`,
})[state.value])
</script>

<template>
  <a v-if="(state === 'lean' || state === 'defined') && info.url" class="tr-badge" :class="`tr-badge-${state}`" :href="info.url" target="_blank" rel="noopener" :title="title">{{ label }}</a>
  <span v-else class="tr-badge" :class="`tr-badge-${state}`" :title="title">{{ label }}</span>
</template>
