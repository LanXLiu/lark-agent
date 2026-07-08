import os
import json
import shutil
import hashlib
import pickle
import logging
from datasketch import MinHash, MinHashLSH
from tqdm import tqdm
import time
import jieba
from typing import Dict, List, Set, Tuple, Optional, Union

from chunker.base import ChunkResult

# 配置参数
LSH_PARAMS = {
    "num_perm": 128,
    "threshold": 0.6,
    "batch_size": 1000,
    "top_k": 20
}

FEATURE_PARAMS = {
    "ngram": 2,
    "stopwords": {"的", "是", "在", "了", "和", "呢", "吗", "我", "你", "他", "这", "那", "不", "都"}
}

logger = logging.getLogger(__name__)

class DeduplicationCore:
    """文本去重核心类"""
    
    def __init__(self):
        self.text_preprocessor = TextPreprocessor()
        self.feature_extractor = FeatureExtractor()
        self.minhash_generator = MinHashGenerator()
        self.lsh_index = LSHIndex()
        self.candidate_ranker = CandidateRanker()
    
    def process(
        self,
        clear_cache: bool = True,
        input_dir: str = "input",
        output_dir: str = "output",
        cache_dir: str = "cache"
    ) -> Tuple[Dict[str, List[Tuple[str, float]]], str, str, str]:
        """
        LSH去重主流程
        返回：相似度结果, 输入目录, 输出目录, 缓存目录
        """
        logger.info("=== 文本去重系统启动 ===")
        
        # 创建目录
        for dir_path in [input_dir, output_dir, cache_dir]:
            os.makedirs(dir_path, exist_ok=True)
        
        # 缓存文件路径
        features_cache_path = os.path.join(cache_dir, "features_cache.pkl")
        minhash_cache_path = os.path.join(cache_dir, "minhash_cache.pkl")
        
        batch_size = LSH_PARAMS["batch_size"]
        loader = DataLoader(input_dir, batch_size=batch_size)
        total_docs = loader.count_total()
        logger.info(f"预估总文档数: {total_docs}，批次大小: {batch_size}")

        # 缓存清理
        if clear_cache:
            shutil.rmtree(cache_dir, ignore_errors=True)
            os.makedirs(cache_dir, exist_ok=True)
            self._clear_cache_files(features_cache_path, minhash_cache_path)
            logger.info("缓存已清理")
        else:
            logger.info("缓存模式开启")

        # 尝试加载缓存
        all_features, all_minhashes = self._load_cache(features_cache_path, minhash_cache_path) if not clear_cache else (None, None)

        # 重新处理数据（如果缓存不存在）
        if not all_features or not all_minhashes:
            logger.info("开始重新处理数据")
            all_features, all_minhashes = self._process_data(loader)
            
            # 保存缓存
            if not clear_cache:
                self._save_cache(all_features, all_minhashes, features_cache_path, minhash_cache_path)
        else:
            logger.info(f"使用缓存数据：特征数={len(all_features)}，MinHash签名数={len(all_minhashes)}")

        # 构建LSH索引和查询
        final_results = self._build_index_and_query(all_minhashes, all_features, input_dir)
        
        return final_results, input_dir, output_dir, cache_dir

    def _process_data(self, loader: 'DataLoader') -> Tuple[Dict[str, Set[int]], Dict[str, Optional[MinHash]]]:
        """处理数据并生成特征和MinHash"""
        all_features = {}
        all_minhashes = {}
        
        for batch in loader.stream_batches(with_raw_line=False):
            if not batch:
                continue
            tokens = self.text_preprocessor.batch_process(batch)
            features = self.feature_extractor.batch_extract(tokens)
            minhashes = self.minhash_generator.batch_generate(features)
            all_features.update(features)
            all_minhashes.update(minhashes)
        
        duplicate_count = loader.get_duplicate_count()
        logger.info(f"整行去重完成：共过滤 {duplicate_count} 个完全重复的行")
        
        return all_features, all_minhashes

    def _build_index_and_query(self, all_minhashes: Dict[str, Optional[MinHash]], 
                             all_features: Dict[str, Set[int]], input_dir: str) -> Dict[str, List[Tuple[str, float]]]:
        """构建索引并查询相似文档"""
        # 构建LSH索引
        logger.info("=== 构建LSH索引 ===")
        valid_pairs = [(doc_id, mh) for doc_id, mh in all_minhashes.items() if mh is not None]
        self.lsh_index.batch_insert({doc_id: mh for doc_id, mh in valid_pairs})

        # 查询与精排
        logger.info("=== 查询与精排 ===")
        final_results = {}
        loader = DataLoader(input_dir, batch_size=LSH_PARAMS["batch_size"])
        
        for batch in loader.stream_batches(with_raw_line=False):
            if not batch:
                continue
            doc_ids = list(batch.keys())
            batch_minhashes = {id: all_minhashes.get(id) for id in doc_ids if id in all_minhashes}
            candidates = self.lsh_index.batch_query(batch_minhashes)
            ranked = self.candidate_ranker.batch_rank(candidates, all_features, LSH_PARAMS["threshold"])
            final_results.update(ranked)

        return final_results

    def _load_cache(self, features_cache_path: str, minhash_cache_path: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        """加载缓存"""
        if os.path.exists(features_cache_path) and os.path.exists(minhash_cache_path):
            try:
                with open(features_cache_path, "rb") as f:
                    all_features = pickle.load(f)
                with open(minhash_cache_path, "rb") as f:
                    all_minhashes = pickle.load(f)
                logger.info("缓存加载成功")
                return all_features, all_minhashes
            except Exception as e:
                logger.error(f"缓存文件损坏: {e}")
                self._clear_cache_files(features_cache_path, minhash_cache_path)
        return None, None

    def _save_cache(self, all_features: Dict, all_minhashes: Dict, features_cache_path: str, minhash_cache_path: str):
        """保存缓存"""
        try:
            with open(features_cache_path, "wb") as f:
                pickle.dump(all_features, f)
            with open(minhash_cache_path, "wb") as f:
                pickle.dump(all_minhashes, f)
            logger.info("缓存保存成功")
        except Exception as e:
            logger.error(f"缓存保存失败: {e}")
            self._clear_cache_files(features_cache_path, minhash_cache_path)

    def _clear_cache_files(self, features_cache_path: str, minhash_cache_path: str):
        """清理缓存文件"""
        for cache_path in [features_cache_path, minhash_cache_path]:
            if os.path.exists(cache_path):
                os.remove(cache_path)
        logger.info("缓存文件已清理")


# 工具函数
def hash_func(value: bytes) -> int:
    sha256_hash = hashlib.sha256(value).digest()
    return int.from_bytes(sha256_hash[:4], byteorder='little', signed=False)

def compute_jaccard(set_a: Set[int], set_b: Set[int]) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union != 0 else 0.0

def log_time(func_name: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            end = time.perf_counter()
            logger.info(f"{func_name}：{end - start:.3f}秒")
            return result
        return wrapper
    return decorator


# 核心组件类
class TextPreprocessor:
    def __init__(self):
        self.stopwords = FEATURE_PARAMS["stopwords"]
    
    @log_time("文本预处理耗时")
    def batch_process(self, texts: Dict[str, str]) -> Dict[str, List[str]]:
        processed = {}
        for doc_id, text in tqdm(texts.items(), desc="预处理文本"):
            if not text or not isinstance(text, str):
                processed[doc_id] = []
                continue
            text = text.strip().replace("\n", "").replace("\t", "").replace(" ", "")
            words = jieba.lcut(text, cut_all=False)
            valid_words = [w for w in words if w not in self.stopwords and len(w) >= 2]
            processed[doc_id] = valid_words
        return processed

class FeatureExtractor:
    @staticmethod
    @log_time("特征提取耗时")
    def batch_extract(tokens_dict: Dict[str, List[str]]) -> Dict[str, Set[int]]:
        n = FEATURE_PARAMS["ngram"]
        features = {}
        for doc_id, tokens in tqdm(tokens_dict.items(), desc="提取特征"):
            if not tokens:
                features[doc_id] = set()
                continue
            if len(tokens) < n:
                features[doc_id] = set([hash_func(token.encode("utf-8")) for token in tokens])
            else:
                ngrams = [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens)-n+1)]
                features[doc_id] = set([hash_func(ng.encode("utf-8")) for ng in ngrams])
        logger.info(f"特征提取完成: 文档数={len(features)}")
        return features

class MinHashGenerator:
    def __init__(self):
        self.num_perm = LSH_PARAMS["num_perm"]
    
    @log_time("MinHash签名生成耗时")
    def batch_generate(self, features_dict: Dict[str, Set[int]]) -> Dict[str, Optional[MinHash]]:
        minhashes = {}
        successful_count = 0
        for doc_id, features in tqdm(features_dict.items(), desc="生成MinHash签名"):
            if not features:
                minhashes[doc_id] = None
                continue
            try:
                m = MinHash(num_perm=self.num_perm, hashfunc=hash_func)
                for feat in features:
                    m.update(feat.to_bytes(length=4, byteorder='little', signed=False))
                minhashes[doc_id] = m
                successful_count += 1
            except:
                minhashes[doc_id] = None
        logger.info(f"MinHash生成完成: 成功={successful_count}, 失败={len(features_dict)-successful_count}")
        return minhashes

class LSHIndex:
    def __init__(self):
        self.num_perm = LSH_PARAMS["num_perm"]
        self.threshold = LSH_PARAMS["threshold"]
        self.index = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        self.all_doc_ids = set()
    
    @log_time("LSH索引构建耗时")
    def batch_insert(self, minhash_dict: Dict[str, Optional[MinHash]]):
        successful_inserts = 0
        for doc_id, mh in tqdm(minhash_dict.items(), desc="构建LSH索引"):
            if mh and doc_id not in self.all_doc_ids:
                self.index.insert(doc_id, mh)
                self.all_doc_ids.add(doc_id)
                successful_inserts += 1
        logger.info(f"索引构建完成: 成功插入 {successful_inserts} 个文档")
    
    @log_time("候选集查询耗时")
    def batch_query(self, minhash_dict: Dict[str, Optional[MinHash]]) -> Dict[str, List[str]]:
        candidates = {}
        for doc_id, mh in tqdm(minhash_dict.items(), desc="查询候选集"):
            if not mh:
                candidates[doc_id] = []
                continue
            res = self.index.query(mh)
            candidates[doc_id] = list(set(res) - {doc_id})[:LSH_PARAMS["top_k"]]
        return candidates

class CandidateRanker:
    @staticmethod
    @log_time("候选集精排耗时")
    def batch_rank(
        candidates: Dict[str, List[str]],
        features_dict: Dict[str, Set[int]],
        threshold: float
    ) -> Dict[str, List[Tuple[str, float]]]:
        ranked_results = {}
        for doc_id, cand_ids in tqdm(candidates.items(), desc="精排候选集"):
            query_feat = features_dict.get(doc_id, set())
            sim_scores = []
            for cand_id in cand_ids:
                cand_feat = features_dict.get(cand_id, set())
                sim = compute_jaccard(query_feat, cand_feat)
                if sim >= threshold:
                    sim_scores.append((cand_id, round(sim, 3)))
            ranked_results[doc_id] = sorted(sim_scores, key=lambda x: x[1], reverse=True)
        logger.info(f"精排完成: 处理 {len(ranked_results)} 个文档")
        return ranked_results

class DataLoader:
    def __init__(self, input_dir: str, batch_size: int = 1000):
        self.input_dir = input_dir
        self.batch_size = batch_size
        self.jsonl_files = [f for f in os.listdir(input_dir) if f.endswith(".jsonl")]
        self.txt_files = [f for f in os.listdir(input_dir) if f.endswith(".txt")]
        self.line_hash_set = set()
        self.duplicate_count = 0
    
    def stream_batches(self, with_raw_line: bool = False) -> Dict[str, Union[str, Tuple[str, str]]]:
        """流式生成批次数据（自动过滤整行重复）"""
        # 处理JSONL文件
        for filename in self.jsonl_files:
            file_path = os.path.join(self.input_dir, filename)
            batch = {}
            with open(file_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    raw_line = line.strip()
                    if not raw_line:
                        continue
                    
                    line_hash = hashlib.md5(raw_line.encode("utf-8")).hexdigest()
                    if line_hash in self.line_hash_set:
                        self.duplicate_count += 1
                        continue
                    
                    self.line_hash_set.add(line_hash)
                    try:
                        data = json.loads(raw_line)
                        doc_id = data.get("id", f"{filename}_line{line_num}")
                        text = data.get("text", "")
                        if doc_id:
                            if with_raw_line:
                                batch[doc_id] = (text, raw_line)
                            else:
                                batch[doc_id] = text
                            if len(batch) >= self.batch_size:
                                yield batch
                                batch = {}
                    except:
                        continue
                if batch:
                    yield batch
        
        # 处理TXT文件
        batch = {}
        for filename in self.txt_files:
            file_path = os.path.join(self.input_dir, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                raw_line = f.read()
                text = raw_line.strip()
            
            line_hash = hashlib.md5(raw_line.encode("utf-8")).hexdigest()
            if line_hash in self.line_hash_set:
                self.duplicate_count += 1
                continue
            
            self.line_hash_set.add(line_hash)
            doc_id = filename
            if with_raw_line:
                batch[doc_id] = (text, raw_line)
            else:
                batch[doc_id] = text
            if len(batch) >= self.batch_size:
                yield batch
                batch = {}
        if batch:
            yield batch

    def count_total(self) -> int:
        """估算总文档数（含重复行）"""
        total = 0
        for f in self.jsonl_files:
            with open(os.path.join(self.input_dir, f), "r", encoding="utf-8") as f_in:
                total += sum(1 for line in f_in if line.strip())
        total += len(self.txt_files)
        return total

    def get_duplicate_count(self) -> int:
        """获取整行重复的总行数"""
        return self.duplicate_count


# 工具函数
def deduplicate_by_similarity(
    similarity_result: Dict[str, List[Tuple[str, float]]],
    keep_strategy: str = "min_id"
) -> List[str]:
    """去重逻辑（处理文本相似度重复）"""
    processed_ids = set()
    kept_ids = []

    for doc_id in similarity_result.keys():
        if doc_id in processed_ids:
            continue
        similar_group = {doc_id}
        for similar_id, sim_score in similarity_result[doc_id]:
            if similar_id not in processed_ids:
                similar_group.add(similar_id)
        if keep_strategy == "min_id":
            kept_id = min(similar_group, key=lambda x: x)
        else:
            kept_id = doc_id
        kept_ids.append(kept_id)
        processed_ids.update(similar_group)

    kept_ids.sort()
    logger.info(f"文本相似度去重完成: 原始 {len(similarity_result)} 个，保留 {len(kept_ids)} 个")
    return kept_ids

def save_deduplicated_data(kept_ids: List[str], input_dir: str, output_dir: str):
    """保存去重结果"""
    output_file = os.path.join(output_dir, "deduplicated_data.jsonl")
    kept_ids_set = set(kept_ids)
    line_hash_set = set()

    with open(output_file, "w", encoding="utf-8") as f_out:
        # 处理JSONL文件
        for filename in os.listdir(input_dir):
            if not filename.endswith(".jsonl"):
                continue
            file_path = os.path.join(input_dir, filename)
            with open(file_path, "r", encoding="utf-8") as f_in:
                for line in tqdm(f_in, desc=f"处理 {filename}"):
                    raw_line = line.strip()
                    if not raw_line:
                        continue
                    
                    line_hash = hashlib.md5(raw_line.encode("utf-8")).hexdigest()
                    if line_hash in line_hash_set:
                        continue
                    line_hash_set.add(line_hash)
                    
                    try:
                        doc = json.loads(raw_line)
                        doc_id = doc.get("id")
                        if doc_id in kept_ids_set:
                            f_out.write(json.dumps(doc, ensure_ascii=False) + "\n")
                    except Exception as e:
                        logger.warning(f"JSON解析失败: {e}")
                        continue
        
        # 处理TXT文件
        for filename in os.listdir(input_dir):
            if not filename.endswith(".txt"):
                continue
            if filename not in kept_ids_set:
                continue
            
            file_path = os.path.join(input_dir, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f_in:
                    raw_line = f_in.read()
                    text = raw_line.strip()
                
                line_hash = hashlib.md5(raw_line.encode("utf-8")).hexdigest()
                if line_hash in line_hash_set:
                    continue
                line_hash_set.add(line_hash)
                
                f_out.write(json.dumps({"id": filename, "text": text}, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning(f"TXT文件处理失败: {e}")
                continue

    logger.info(f"去重结果已保存至: {output_file}")
    return output_file


def deduplicate_chunks_with_lsh(
    chunks: List[ChunkResult],
    *,
    threshold: float = 0.9,
    min_chars: int = 80,
    same_title_only: bool = True,
) -> List[ChunkResult]:
    """Conservative near-duplicate removal within one document's chunks.

    This is intentionally stricter than the batch file-level LSH flow:
    - only compares chunks from the same document call;
    - defaults to same-title comparison;
    - ignores short chunks because headings and labels are better handled by
      exact/title-only deduplication.
    """
    if len(chunks) <= 1:
        return chunks

    preprocessor = TextPreprocessor()
    extractor = FeatureExtractor()
    texts = {
        str(idx): chunk.text
        for idx, chunk in enumerate(chunks)
        if len((chunk.text or "").strip()) >= min_chars
    }
    if len(texts) <= 1:
        return chunks

    tokens = preprocessor.batch_process(texts)
    features = extractor.batch_extract(tokens)
    removed_indexes: set[int] = set()

    for i, left in enumerate(chunks):
        if i in removed_indexes or str(i) not in features:
            continue
        left_features = features[str(i)]
        if not left_features:
            continue

        for j in range(i + 1, len(chunks)):
            if j in removed_indexes or str(j) not in features:
                continue
            right = chunks[j]
            if same_title_only and _chunk_title(left) != _chunk_title(right):
                continue

            score = compute_jaccard(left_features, features[str(j)])
            if score >= threshold:
                removed_indexes.add(_choose_chunk_to_remove(left, right, i, j))

    kept = [chunk for idx, chunk in enumerate(chunks) if idx not in removed_indexes]
    return [
        ChunkResult(
            text=chunk.text,
            index=new_index,
            token_count=len(chunk.text),
            metadata=chunk.metadata,
        )
        for new_index, chunk in enumerate(kept)
    ]


def _chunk_title(chunk: ChunkResult) -> str:
    title = str(chunk.metadata.get("title") or "").strip()
    if title:
        return title
    first_line = (chunk.text or "").strip().splitlines()[0] if (chunk.text or "").strip() else ""
    return first_line.lstrip("#").strip()


def _choose_chunk_to_remove(
    left: ChunkResult,
    right: ChunkResult,
    left_index: int,
    right_index: int,
) -> int:
    """Keep the richer chunk; when equal, keep the earlier one."""
    left_len = len(left.text or "")
    right_len = len(right.text or "")
    if left_len == right_len:
        return right_index
    return left_index if left_len < right_len else right_index