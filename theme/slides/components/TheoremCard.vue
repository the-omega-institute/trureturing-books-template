<!--
  A numbered statement with its verification state, mirroring the book's theorem environment:
    <TheoremCard label="定理 1.2" title="亏量只取三个值" gid="D5/S1/Deficit/DeficitThreeValued.deficit_three_valued">

    $$c(v_1, v_2) \in \{-1, 0, 1\}$$

    </TheoremCard>
  Props: label (kind and number, as the book prints it), title, gid (Lean GID; must be in
  trureturing.lock.json and name a Lean theorem), status ('open' for an open problem, 'argued' for an
  unverified argument, 'written-proof' for a source proof without a matching Lean declaration; no gid), kind ('definition' for a definition card: neutral cyan rule and LEAN DEF badge,
  never the green LEAN ✓; the GID may name a Lean def and the footer links it), cite (the id of the
  matching environment in the book, e.g. thm-deficit; ./tbook check then verifies that label and GID
  agree with the book). The statement goes in the default slot (Markdown and KaTeX work when it is
  separated by blank lines; keep it unindented).
-->
<script setup lang="ts">
import { computed } from 'vue'
import LeanBadge from './LeanBadge.vue'
import { leanInfo, leanState } from '../lean'
import { t } from '../i18n'

const props = defineProps<{ label?: string, title?: string, gid?: string, status?: 'open' | 'argued' | 'written-proof', kind?: string, cite?: string, doi?: string, source?: string, request?: string }>()
const info = computed(() => leanInfo(props.gid))
const state = computed(() => leanState(info.value, props.status, props.kind))
const kindClass = computed(() => props.kind === 'definition' ? 'tr-thm-def' : '')
const doiURL = computed(() => props.doi ? 'https://doi.org/' + props.doi.split('/').map(encodeURIComponent).join('/') : '')
</script>

<template>
  <section class="tr-thm" :class="[`tr-thm-${state}`, kindClass]" :data-cite="props.cite">
    <header class="tr-thm-head">
      <span class="tr-thm-label">{{ props.label }}</span>
      <span v-if="props.title" class="tr-thm-title">{{ props.title }}</span>
      <LeanBadge :gid="props.gid" :status="props.status" :kind="props.kind" />
    </header>
    <div class="tr-thm-body"><slot /></div>
    <footer class="tr-thm-decl">
      <template v-if="state === 'written-proof'">
        <span>DOI: <a :href="doiURL" target="_blank" rel="noopener">{{ props.doi }}</a> · {{ props.source }} · <a :href="props.request" target="_blank" rel="noopener">trureturing-requests</a></span>
      </template>
      <template v-else-if="props.gid">
        <span class="tr-thm-glyph" aria-hidden="true">λ</span>
        <a v-if="info.url" :href="info.url" target="_blank" rel="noopener"><code>{{ info.name }}</code></a>
        <code v-else>{{ info.name }}</code>
      </template>
      <span v-else class="tr-thm-none">{{ props.status === 'written-proof' ? t('badge.written_proof_title') : props.status === 'argued' ? t('slides.badge_argued_title') : t('slides.no_lean') }}</span>
    </footer>
  </section>
</template>
