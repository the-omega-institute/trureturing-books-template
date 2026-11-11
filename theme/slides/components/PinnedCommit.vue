<!-- Current publication basis, supplied by the existing virtual lock module. -->
<script setup lang="ts">
import { pinned } from '../lean'
</script>

<template>
  <a v-if="pinned.short" :href="pinned.url" class="mono" target="_blank" rel="noopener">{{ pinned.short }}</a>
</template>
