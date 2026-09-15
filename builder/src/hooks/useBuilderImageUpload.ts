import { useCallback, useRef, useState } from 'react'

import type { useBuilderData } from './useBuilderData'
import { MAX_IMAGE_BYTES } from '../lib/builderConstants'
import { getErrorMessage } from '../lib/errors'
import type { BuilderImageFile, BuilderImageListResponse, BuilderTemplateDoctype } from '../types'
import type { NoticeKind, NoticeOptions } from '../components/notificationContext'

type Notify = (value: unknown, kind?: NoticeKind, options?: NoticeOptions) => void

type ImagePickerScope = 'template' | 'public'

type ImageUploadOptions = {
  fileUpload: ReturnType<typeof useBuilderData>['fileUpload']
  listImages: ReturnType<typeof useBuilderData>['listImages']
  attachImage: ReturnType<typeof useBuilderData>['attachImage']
  templateName: string
  templateDoctype: BuilderTemplateDoctype
  notify: Notify
  updateContent: (blockId: string, key: string, value: unknown) => void
}

const DEFAULT_MAX_WIDTH = 1600
const IMAGE_PAGE_LENGTH = 36
type MaxImageWidth = number | 'auto'

function shouldOptimizeByDefault(file: File) {
  return file.size > 200 * 1024 && file.type.startsWith('image/') && file.type !== 'image/gif' && file.type !== 'image/svg+xml'
}

export function useBuilderImageUpload({ fileUpload, listImages, attachImage, templateName, templateDoctype, notify, updateContent }: ImageUploadOptions) {
  const [pendingImageBlock, setPendingImageBlock] = useState<string | null>(null)
  const [imagePickerBlock, setImagePickerBlock] = useState<string | null>(null)
  const [imagePickerScope, setImagePickerScope] = useState<ImagePickerScope>('template')
  const [imageSearch, setImageSearch] = useState('')
  const [imageLibrary, setImageLibrary] = useState<BuilderImageFile[]>([])
  const [imageLibraryLoading, setImageLibraryLoading] = useState(false)
  const [imageLibraryLoadingMore, setImageLibraryLoadingMore] = useState(false)
  const [imageLibraryHasMore, setImageLibraryHasMore] = useState(false)
  const [imageLibraryNextStart, setImageLibraryNextStart] = useState(0)
  const [imageLibraryError, setImageLibraryError] = useState<unknown>(null)
  const [optimizeImages, setOptimizeImages] = useState(true)
  const [maxImageWidth, setMaxImageWidth] = useState<MaxImageWidth>('auto')
  const searchTimerRef = useRef<number | undefined>(undefined)

  const normalizeImageList = useCallback((message: BuilderImageListResponse | BuilderImageFile[] | undefined, fallbackStart: number) => {
    if (Array.isArray(message)) {
      return { rows: message, hasMore: message.length >= IMAGE_PAGE_LENGTH, nextStart: fallbackStart + message.length }
    }
    const rows = Array.isArray(message?.rows) ? message.rows : []
    return {
      rows,
      hasMore: Boolean(message?.has_more),
      nextStart: Number(message?.next_start ?? fallbackStart + rows.length) || 0,
    }
  }, [])

  const loadImages = useCallback(async (scope = imagePickerScope, search = imageSearch, options?: { append?: boolean; start?: number }) => {
    if (!templateName) return
    const append = Boolean(options?.append)
    const start = Math.max(0, Number(options?.start || 0))
    if (append) setImageLibraryLoadingMore(true)
    else setImageLibraryLoading(true)
    setImageLibraryError(null)
    try {
      const response = await listImages.call({ template_name: templateName, template_doctype: templateDoctype, scope, search, start, page_length: IMAGE_PAGE_LENGTH })
      const result = normalizeImageList(response.message as BuilderImageListResponse | BuilderImageFile[] | undefined, start)
      setImageLibrary((current) => append ? [...current, ...result.rows] : result.rows)
      setImageLibraryHasMore(result.hasMore)
      setImageLibraryNextStart(result.nextStart)
    } catch (error) {
      if (!append) {
        setImageLibrary([])
        setImageLibraryHasMore(false)
        setImageLibraryNextStart(0)
      }
      setImageLibraryError(error)
    } finally {
      if (append) setImageLibraryLoadingMore(false)
      else setImageLibraryLoading(false)
    }
  }, [imagePickerScope, imageSearch, listImages, normalizeImageList, templateDoctype, templateName])

  const openImagePicker = useCallback((blockId: string) => {
    setImagePickerBlock(blockId)
    setImagePickerScope('template')
    setImageSearch('')
    void loadImages('template', '', { start: 0 })
  }, [loadImages])

  const closeImagePicker = useCallback(() => {
    setImagePickerBlock(null)
    setImageLibraryError(null)
  }, [])

  const changeImageScope = useCallback((scope: ImagePickerScope) => {
    setImagePickerScope(scope)
    void loadImages(scope, imageSearch, { start: 0 })
  }, [imageSearch, loadImages])

  const changeImageSearch = useCallback((value: string) => {
    setImageSearch(value)
    if (searchTimerRef.current) window.clearTimeout(searchTimerRef.current)
    searchTimerRef.current = window.setTimeout(() => void loadImages(imagePickerScope, value, { start: 0 }), 300)
  }, [imagePickerScope, loadImages])

  const uploadImage = useCallback(async (blockId: string, file: File) => {
    if (!file.type.startsWith('image/')) {
      notify('Choose an image file.', 'error')
      return
    }
    if (file.size > MAX_IMAGE_BYTES) {
      notify('Images must be 10 MB or smaller.', 'error')
      return
    }
    const optimize = optimizeImages && shouldOptimizeByDefault(file)
    const uploadOptions = {
      isPrivate: false,
      folder: 'Home/Attachments',
      doctype: templateDoctype,
      docname: templateName,
      otherData: optimize
        ? { optimize: '1', ...(maxImageWidth === 'auto' ? {} : { max_width: String(maxImageWidth || DEFAULT_MAX_WIDTH) }) }
        : {},
    }
    setPendingImageBlock(blockId)
    try {
      const result = await fileUpload.upload(file, uploadOptions)
      updateContent(blockId, 'src', result.file_url)
      if (!String(result.file_url || '').includes('/private/')) {
        notify(optimize ? 'Image uploaded and optimized' : 'Image uploaded', 'success')
      } else {
        notify('Image uploaded, but it looks private. Use a public image for emails.', 'warning')
      }
      closeImagePicker()
      void loadImages('template', '', { start: 0 })
    } catch (error) {
      notify(getErrorMessage(error, 'Image upload failed.'), 'error')
    } finally {
      setPendingImageBlock(null)
    }
  }, [closeImagePicker, fileUpload, loadImages, maxImageWidth, notify, optimizeImages, templateDoctype, templateName, updateContent])

  const uploadInspectorImage = useCallback((blockId: string, file: File) => { void uploadImage(blockId, file) }, [uploadImage])

  const selectExistingImage = useCallback(async (fileName: string) => {
    if (!imagePickerBlock) return
    setPendingImageBlock(imagePickerBlock)
    try {
      const response = await attachImage.call({ template_name: templateName, template_doctype: templateDoctype, file_name: fileName })
      const file = response.message
      updateContent(imagePickerBlock, 'src', file.file_url)
      notify('Existing image selected', 'success')
      closeImagePicker()
      void loadImages('template', '', { start: 0 })
    } catch (error) {
      notify(getErrorMessage(error, 'Image could not be selected.'), 'error')
    } finally {
      setPendingImageBlock(null)
    }
  }, [attachImage, closeImagePicker, imagePickerBlock, loadImages, notify, templateDoctype, templateName, updateContent])

  const uploadImageFromPicker = useCallback((file: File) => {
    if (imagePickerBlock) void uploadImage(imagePickerBlock, file)
  }, [imagePickerBlock, uploadImage])

  const loadMoreImages = useCallback(() => {
    if (!imageLibraryHasMore || imageLibraryLoading || imageLibraryLoadingMore) return
    void loadImages(imagePickerScope, imageSearch, { append: true, start: imageLibraryNextStart })
  }, [imageLibraryHasMore, imageLibraryLoading, imageLibraryLoadingMore, imageLibraryNextStart, imagePickerScope, imageSearch, loadImages])

  const uploadProgress = pendingImageBlock ? Math.max(1, Math.min(100, fileUpload.progress || 1)) : 0

  return {
    pendingImageBlock,
    uploadProgress,
    chooseImage: openImagePicker,
    uploadInspectorImage,
    imagePickerBlock,
    imagePickerScope,
    imageSearch,
    imageLibrary,
    imageLibraryLoading,
    imageLibraryLoadingMore,
    imageLibraryHasMore,
    imageLibraryNextStart,
    imageLibraryError,
    optimizeImages,
    maxImageWidth,
    setOptimizeImages,
    setMaxImageWidth,
    closeImagePicker,
    changeImageScope,
    changeImageSearch,
    refreshImageLibrary: loadImages,
    loadMoreImages,
    selectExistingImage,
    uploadImageFromPicker,
  }
}

export type { ImagePickerScope }
