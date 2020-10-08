# coding=utf-8
# Copyright 2020 The Trax Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Lint as: python3
"""Transformer models: encoder, decoder, language model, and encoder-decoder.

The "Transformer" name and network architecture were introduced in the paper
[Attention Is All You Need](https://arxiv.org/abs/1706.03762).
"""

from trax import layers as tl
from trax.models.reformer import reformer


def ConfigurableTransformerEncoder(vocab_size,
                                   n_classes=10,
                                   d_model=512,
                                   d_ff=2048,
                                   n_layers=6,
                                   n_heads=8,
                                   max_len=2048,
                                   dropout=0.1,
                                   dropout_shared_axes=None,
                                   mode='train',
                                   ff_activation=tl.Relu,
                                   ff_dropout=0.1,
                                   ff_chunk_size=0,
                                   ff_use_sru=0,
                                   ff_sparsity=0,
                                   attention_type=tl.Attention):
  """Returns a Transformer encoder merged with an N-way categorization head.

  This model performs text categorization:

    - input: rank 2 tensor representing a batch of text strings via token IDs
      plus padding markers; shape is (batch_size, sequence_length). The tensor
      elements are integers in `range(vocab_size)`, and `0` values mark padding
      positions.

    - output: rank 2 tensor representing a batch of log-probability
      distributions over N categories; shape is (batch_size, `n_classes`).

  Args:
    vocab_size: Input vocabulary size -- each element of the input tensor
        should be an integer in `range(vocab_size)`. These integers typically
        represent token IDs from a vocabulary-based tokenizer.
    n_classes: Final dimension of the output tensors, representing N-way
        classification.
    d_model: Final dimension of tensors at most points in the model, including
        the initial embedding output.
    d_ff: Size of special dense layer in the feed-forward part of each encoder
        block.
    n_layers: Number of encoder blocks. Each block includes attention, dropout,
        residual, feed-forward (`Dense`), and activation layers.
    n_heads: Number of attention heads.
    max_len: Maximum symbol length for positional encoding.
    dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout within an encoder block.
    dropout_shared_axes: Tensor axes on which to share a dropout mask.
        Sharing along batch and sequence axes (`dropout_shared_axes=(0,1)`) is
        a useful way to save memory and apply consistent masks to activation
        vectors at different sequence positions.
    mode: If `'train'`, each encoder block will include dropout; else, it will
        pass all values through unaltered.
    ff_activation: Type of activation function at the end of each encoder
        block; must be an activation-type subclass of `Layer`.
    ff_dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout after the FF dense layer.
    ff_chunk_size: int; if > 0, chunk feed-forward into this-sized chunks
    ff_use_sru: int; if > 0, we use this many SRU layers instead of feed-forward
    ff_sparsity: int, if > 0 use sparse feed-forward block with this sparsity
    attention_type: The attention layer to use for the encoder part.

  Returns:
    A Transformer model that maps strings (conveyed via token IDs) to
    probability-like activations over a range of output classes.
  """
  positional_encoder = [
      tl.Embedding(vocab_size, d_model),
      tl.Dropout(rate=dropout, shared_axes=dropout_shared_axes, mode=mode),
      tl.PositionalEncoding(max_len=max_len)]

  # pylint: disable=g-complex-comprehension
  encoder_blocks = [
      _EncoderBlock(d_model, d_ff, n_heads, dropout, dropout_shared_axes,
                    mode, ff_activation, ff_dropout, ff_chunk_size, ff_use_sru,
                    ff_sparsity, attention_type)
      for i in range(n_layers)]
  # pylint: enable=g-complex-comprehension

  # Assemble and return the model.
  return tl.Serial(                               # toks
      # Encode.
      tl.Branch(
          positional_encoder, tl.PaddingMask()),  # vecs masks
      encoder_blocks,                             # vecs masks
      tl.Select([0], n_in=2),                     # vecs
      tl.LayerNorm(),                             # vecs

      # Map to output categories.
      tl.Mean(axis=1),                            # vecs
      tl.Dense(n_classes),                        # vecs
      tl.LogSoftmax(),                            # vecs
  )


def ConfigurableTransformerDecoder(vocab_size=None,
                                   d_model=512,
                                   d_ff=2048,
                                   n_layers=6,
                                   n_heads=8,
                                   max_len=2048,
                                   dropout=0.1,
                                   dropout_shared_axes=None,
                                   mode='train',
                                   ff_activation=tl.Relu,
                                   ff_dropout=0.1,
                                   ff_chunk_size=0,
                                   ff_use_sru=0,
                                   ff_sparsity=0,
                                   attention_type=tl.CausalAttention):
  """Returns a Transformer decoder.

  This model maps sequential inputs to sequential outputs:

    - input if `vocab_size` is specified: rank 2 tensor representing a batch
      of text strings via token IDs plus padding markers; shape is
      (batch_size, sequence_length). The tensor elements are integers in
      `range(vocab_size)`, and `0` values mark padding positions.

    - input if `vocab_size` is None: rank 2 tensor representing a batch
      of activation vectors; shape is (batch_size, sequence_length, `d_model`).

    - output: rank 3 tensor with shape (batch_size, sequence_length, `d_model`).

  The model uses causal attention and does *not* shift the input to the right.
  Thus, the output for position `t` is based on inputs up to and including
  position `t`.

  Args:
    vocab_size: If specified, gives the input vocabulary size -- each element
        of the input tensor should be an integer in `range(vocab_size)`.
        If None, indicates that the model expects as input floating point
        vectors, each with `d_model` components.
    d_model: Final dimension of tensors at most points in the model, including
        the initial embedding output.
    d_ff: Size of special dense layer in the feed-forward part of each decoder
        block.
    n_layers: Number of decoder blocks. Each block includes attention, dropout,
        residual, feed-forward (`Dense`), and activation layers.
    n_heads: Number of attention heads.
    max_len: Maximum symbol length for positional encoding.
    dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout within a decoder block.
    dropout_shared_axes: Tensor axes on which to share a dropout mask.
        Sharing along batch and sequence axes (`dropout_shared_axes=(0,1)`) is
        a useful way to save memory and apply consistent masks to activation
        vectors at different sequence positions.
    mode: If `'train'`, each decoder block will include dropout; else, it will
        pass all values through unaltered.
    ff_activation: Type of activation function at the end of each decoder
        block; must be an activation-type subclass of `Layer`.
    ff_dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout after the FF dense layer.
    ff_chunk_size: int; if > 0, chunk feed-forward into this-sized chunks
    ff_use_sru: int; if > 0, we use this many SRU layers instead of feed-forward
    ff_sparsity: int, if > 0 use sparse feed-forward block with this sparsity
    attention_type: The attention layer to use for the decoder part.

  Returns:
    If `vocab_size` is defined: a Transformer model that maps strings (conveyed
    via token IDs) to sequences of activation vectors.

    If `vocab_size` is None: a Transformer model that maps sequences of
    activation vectors to sequences of activation vectors.
  """
  positional_encoder = [
      (tl.Embedding(vocab_size, d_model) if vocab_size is not None
       else tl.Dense(d_model)),
      tl.Dropout(rate=dropout, shared_axes=dropout_shared_axes, mode=mode),
      tl.PositionalEncoding(max_len=max_len)]

  # pylint: disable=g-complex-comprehension
  decoder_blocks = [
      _DecoderBlock(d_model, d_ff, n_heads,
                    dropout, dropout_shared_axes, mode, ff_activation,
                    ff_dropout, ff_chunk_size, ff_use_sru, ff_sparsity,
                    attention_type)
      for i in range(n_layers)]
  # pylint: enable=g-complex-comprehension

  # Assemble and return the model.
  return tl.Serial(        # toks
      positional_encoder,  # vecs
      decoder_blocks,      # vecs
      tl.LayerNorm(),      # vecs
  )


def ConfigurableTransformerLM(vocab_size,
                              d_model=512,
                              d_ff=2048,
                              n_layers=6,
                              n_heads=8,
                              max_len=2048,
                              dropout=0.1,
                              dropout_shared_axes=None,
                              mode='train',
                              ff_activation=tl.Relu,
                              ff_dropout=0.1,
                              ff_chunk_size=0,
                              ff_use_sru=0,
                              ff_sparsity=0,
                              attention_type=tl.CausalAttention):
  """Returns a Transformer language model.

  This model performs autoregressive language modeling:

    - input: rank 2 tensor representing a batch of text strings via token IDs
      plus padding markers; shape is (batch_size, sequence_length). The tensor
      elements are integers in `range(vocab_size)`, and `0` values mark padding
      positions.

    - output: rank 3 tensor representing a batch of log-probability
      distributions for each sequence position over possible token IDs;
      shape is (batch_size, sequence_length, `vocab_size`).

  This model uses only the decoder part of the overall Transformer.

  Args:
    vocab_size: Input vocabulary size -- each element of the input tensor
        should be an integer in `range(vocab_size)`. These integers typically
        represent token IDs from a vocabulary-based tokenizer.
    d_model: Final dimension of tensors at most points in the model, including
        the initial embedding output.
    d_ff: Size of special dense layer in the feed-forward part of each encoder
        block.
    n_layers: Number of encoder blocks. Each block includes attention, dropout,
        residual, feed-forward (`Dense`), and activation layers.
    n_heads: Number of attention heads.
    max_len: Maximum symbol length for positional encoding.
    dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout within an encoder block.
    dropout_shared_axes: Tensor axes on which to share a dropout mask.
        Sharing along batch and sequence axes (`dropout_shared_axes=(0,1)`) is
        a useful way to save memory and apply consistent masks to activation
        vectors at different sequence positions.
    mode: If `'predict'`, use fast inference. If `'train'`, each encoder block
        will include dropout; else, it will pass all values through unaltered.
    ff_activation: Type of activation function at the end of each encoder
        block; must be an activation-type subclass of `Layer`.
    ff_dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout after the FF dense layer.
    ff_chunk_size: int; if > 0, chunk feed-forward into this-sized chunks
    ff_use_sru: int; if > 0, we use this many SRU layers instead of feed-forward
    ff_sparsity: int, if > 0 use sparse feed-forward block with this sparsity
    attention_type: The attention layer to use for the decoder part.

  Returns:
    A Transformer language model as a layer that maps from a tensor of tokens
    to activations over a vocab set.
  """
  positional_encoder = [
      tl.Embedding(vocab_size, d_model),
      tl.Dropout(rate=dropout, shared_axes=dropout_shared_axes, mode=mode),
      tl.PositionalEncoding(max_len=max_len, mode=mode)]

  # pylint: disable=g-complex-comprehension
  decoder_blocks = [
      _DecoderBlock(d_model, d_ff, n_heads,
                    dropout, dropout_shared_axes, mode, ff_activation,
                    ff_dropout, ff_chunk_size, ff_use_sru, ff_sparsity,
                    attention_type)
      for i in range(n_layers)]
  # pylint: enable=g-complex-comprehension

  # Assemble and return the model.
  return tl.Serial(              # tokens (or chunked tuple of tokens)
      tl.ShiftRight(mode=mode),  # toks
      positional_encoder,        # vecs
      decoder_blocks,            # vecs
      tl.LayerNorm(),            # vecs
      tl.Dense(vocab_size),      # vecs
      tl.LogSoftmax(),           # vecs
  )


def ConfigurableTransformer(input_vocab_size,
                            output_vocab_size=None,
                            d_model=512,
                            d_ff=2048,
                            n_encoder_layers=6,
                            n_decoder_layers=6,
                            n_heads=8,
                            max_len=2048,
                            dropout=0.1,
                            dropout_shared_axes=None,
                            mode='train',
                            ff_activation=tl.Relu,
                            ff_dropout=0.1,
                            ff_chunk_size=0,
                            ff_use_sru=0,
                            ff_sparsity=0,
                            encoder_attention_type=tl.Attention,
                            encoder_decoder_attention_type=tl.CausalAttention):
  """Returns a full Transformer model.

  This model is an encoder-decoder that performs tokenized string-to-string
  ("source"-to-"target") transduction:

    - inputs (2):

        - source: rank 2 tensor representing a batch of text strings via token
          IDs plus padding markers; shape is (batch_size, sequence_length). The
          tensor elements are integers in `range(input_vocab_size)`, and `0`
          values mark padding positions.

        - target: rank 2 tensor representing a batch of text strings via token
          IDs plus padding markers; shape is (batch_size, sequence_length). The
          tensor elements are integers in `range(output_vocab_size)`, and `0`
          values mark padding positions.

    - output: rank 3 tensor representing a batch of log-probability
      distributions for each sequence position over possible token IDs;
      shape is (batch_size, sequence_length, `vocab_size`).

  An example use would be to translate (tokenized) sentences from English to
  German.

  Args:
    input_vocab_size: Input vocabulary size -- each element of the input tensor
        should be an integer in `range(vocab_size)`. These integers typically
        represent token IDs from a vocabulary-based tokenizer.
    output_vocab_size: If specified, gives the vocabulary size for the targets;
        if None, then input and target integers (token IDs) are assumed to come
        from the same vocabulary.
    d_model: Final dimension of tensors at most points in the model, including
        the initial embedding output.
    d_ff: Size of special dense layer in the feed-forward part of each encoder
        and decoder block.
    n_encoder_layers: Number of encoder blocks.
    n_decoder_layers: Number of decoder blocks.
    n_heads: Number of attention heads.
    max_len: Maximum symbol length for positional encoding.
    dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout within an encoder/decoder block.
    dropout_shared_axes: Tensor axes on which to share a dropout mask.
        Sharing along batch and sequence axes (`dropout_shared_axes=(0,1)`) is
        a useful way to save memory and apply consistent masks to activation
        vectors at different sequence positions.
    mode: If `'predict'`, use fast inference. If `'train'`, each encoder/decoder
        block will include dropout; else, it will pass all values through
        unaltered.
    ff_activation: Type of activation function at the end of each
        encoder/decoder block; must be an activation-type subclass of `Layer`.
    ff_dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout after the FF dense layer.
    ff_chunk_size: int; if > 0, chunk feed-forward into this-sized chunks
    ff_use_sru: int; if > 0, we use this many SRU layers instead of feed-forward
    ff_sparsity: int, if > 0 use sparse feed-forward block with this sparsity
    encoder_attention_type: The attention layer to use for the encoder part.
    encoder_decoder_attention_type: The attention layer to use for the
      encoder-decoder attention.

  Returns:
    A Transformer model as a layer that maps from a source-target tokenized
    text pair to activations over a vocab set.
  """
  def Embedder(vocab_size):  # tokens --> vectors
    return [
        tl.Embedding(vocab_size, d_model),
        tl.Dropout(rate=dropout, shared_axes=dropout_shared_axes, mode=mode),
    ]

  in_embedder = Embedder(input_vocab_size)
  out_embedder = (in_embedder if output_vocab_size is None
                  else Embedder(output_vocab_size))

  # Positional encodings are not shared between encoder and decoder.
  # Since encoder doesn't run stepwise, we do not use predict mode there.
  encoder_mode = 'eval' if mode == 'predict' else mode
  in_encoder = in_embedder + [
      tl.PositionalEncoding(max_len=max_len, mode=encoder_mode)
  ]
  out_encoder = out_embedder + [
      tl.PositionalEncoding(max_len=max_len, mode=mode)
  ]

  if output_vocab_size is None:
    output_vocab_size = input_vocab_size

  # pylint: disable=g-complex-comprehension
  encoder_blocks = [
      _EncoderBlock(d_model, d_ff, n_heads, dropout, dropout_shared_axes,
                    mode, ff_activation, ff_dropout, ff_chunk_size,
                    ff_use_sru, ff_sparsity, encoder_attention_type)
      for i in range(n_encoder_layers)]
  # pylint: enable=g-complex-comprehension

  encoder = tl.Serial(
      in_encoder,
      encoder_blocks,
      tl.LayerNorm()
  )
  if mode == 'predict':
    encoder = tl.Cache(encoder)

  # pylint: disable=g-complex-comprehension
  encoder_decoder_blocks = [
      _EncoderDecoderBlock(d_model, d_ff, n_heads, dropout, dropout_shared_axes,
                           mode, ff_activation, ff_dropout, ff_chunk_size,
                           ff_use_sru, ff_sparsity,
                           encoder_decoder_attention_type)
      for i in range(n_decoder_layers)]
  # pylint: enable=g-complex-comprehension

  # Assemble and return the model.
  return tl.Serial(
      # Input: encoder_side_tokens, decoder_side_tokens
      # Copy decoder tokens for use in loss.
      tl.Select([0, 1, 1]),               # tok_e tok_d tok_d

      # Encode.
      tl.Branch([], tl.PaddingMask()),    # tok_e masks ..... .....
      encoder,                            # vec_e ..... ..... .....

      # Decode.
      tl.Select([2, 1, 0]),               # tok_d masks vec_e .....
      tl.ShiftRight(mode=mode),           # tok_d ..... ..... .....
      out_encoder,                        # vec_d ..... ..... .....
      tl.Branch(
          [], tl.EncoderDecoderMask()),   # vec_d masks ..... .....
      encoder_decoder_blocks,             # vec_d masks ..... .....
      tl.LayerNorm(),                     # vec_d ..... ..... .....

      # Map to output vocab.
      tl.Select([0], n_in=3),             # vec_d tok_d
      tl.Dense(output_vocab_size),        # vec_d .....
      tl.LogSoftmax(),                    # vec_d .....
  )


def _EncoderBlock(d_model, d_ff, n_heads,
                  dropout, dropout_shared_axes, mode, ff_activation,
                  ff_dropout, ff_chunk_size, ff_use_sru, ff_sparsity,
                  attention_type):
  """Returns a list of layers that implements a Transformer encoder block.

  The input to the block is a pair, (activations, mask), where the mask was
  created from the original source tokens to prevent attending to the padding
  part of the input.

  Args:
    d_model: Final dimension of tensors at most points in the model, including
        the initial embedding output.
    d_ff: Size of special dense layer in the feed-forward part of each block.
    n_heads: Number of attention heads.
    dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout within a block.
    dropout_shared_axes: Tensor axes on which to share a dropout mask.
        Sharing along batch and sequence axes (`dropout_shared_axes=(0,1)`) is
        a useful way to save memory and apply consistent masks to activation
        vectors at different sequence positions.
    mode: If `'train'`, each block will include dropout; else, it will
        pass all values through unaltered.
    ff_activation: Type of activation function at the end of each block; must
        be an activation-type subclass of `Layer`.
    ff_dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout after the FF dense layer.
    ff_chunk_size: int; if > 0, chunk feed-forward into this-sized chunks
    ff_use_sru: int; if > 0, we use this many SRU layers instead of feed-forward
    ff_sparsity: int, if > 0 use sparse feed-forward block with this sparsity
    attention_type: The attention layer to use.

  Returns:
    A list of layers that maps (activations, mask) to (activations, mask).
  """
  # TODO(afrozm): Check if masked should be True
  # TODO(afrozm): Check if masked should be True
  # TODO(afrozm): Check if masked should be True
  attention = reformer.ApplyAttentionLayer(
      attention_type,
      d_model,
      n_heads,
      d_model // n_heads,
      d_model // n_heads,
      causal=False,
      masked=True,
      attention_dropout=dropout,
      output_dropout=dropout,
      mode=mode)

  feed_forward = reformer.FeedForwardWithOptions(d_model, d_ff, dropout,
                                                 dropout_shared_axes,
                                                 ff_activation, ff_dropout,
                                                 ff_chunk_size, ff_use_sru,
                                                 ff_sparsity, mode)

  dropout_ = tl.Dropout(
      rate=dropout, shared_axes=dropout_shared_axes, mode=mode)

  return [
      tl.Residual(
          tl.LayerNorm(),
          attention,
          dropout_,
      ),
      tl.Residual(
          feed_forward
      ),
  ]


def _DecoderBlock(d_model, d_ff, n_heads,
                  dropout, dropout_shared_axes, mode, ff_activation,
                  ff_dropout, ff_chunk_size, ff_use_sru, ff_sparsity,
                  attention_type):
  """Returns a list of layers that implements a Transformer decoder block.

  The input is an activation tensor.

  Args:
    d_model: Final dimension of tensors at most points in the model, including
        the initial embedding output.
    d_ff: Size of special dense layer in the feed-forward part of each block.
    n_heads: Number of attention heads.
    dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout within a block.
    dropout_shared_axes: Tensor axes on which to share a dropout mask.
        Sharing along batch and sequence axes (`dropout_shared_axes=(0,1)`) is
        a useful way to save memory and apply consistent masks to activation
        vectors at different sequence positions.
    mode: If `'train'`, each block will include dropout; else, it will
        pass all values through unaltered.
    ff_activation: Type of activation function at the end of each block; must
        be an activation-type subclass of `Layer`.
    ff_dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout after the FF dense layer.
    ff_chunk_size: int; if > 0, chunk feed-forward into this-sized chunks
    ff_use_sru: int; if > 0, we use this many SRU layers instead of feed-forward
    ff_sparsity: int, if > 0 use sparse feed-forward block with this sparsity
    attention_type: The attention layer to use.

  Returns:
    A list of layers that maps an activation tensor to an activation tensor.
  """
  # TODO(afrozm): Check if masked should be False
  # TODO(afrozm): Check if masked should be False
  # TODO(afrozm): Check if masked should be False
  causal_attention = reformer.ApplyAttentionLayer(
      attention_type,
      d_model,
      n_heads,
      d_model // n_heads,
      d_model // n_heads,
      causal=True,
      masked=False,
      attention_dropout=dropout,
      output_dropout=dropout,
      mode=mode)

  feed_forward = reformer.FeedForwardWithOptions(d_model, d_ff, dropout,
                                                 dropout_shared_axes,
                                                 ff_activation, ff_dropout,
                                                 ff_chunk_size, ff_use_sru,
                                                 ff_sparsity, mode)

  dropout_ = tl.Dropout(
      rate=dropout, shared_axes=dropout_shared_axes, mode=mode)

  return [
      tl.Residual(
          tl.LayerNorm(),
          causal_attention,
          dropout_,
      ),
      tl.Residual(
          feed_forward
      ),
  ]


def _EncoderDecoderBlock(d_model, d_ff, n_heads,
                         dropout, dropout_shared_axes, mode, ff_activation,
                         ff_dropout, ff_chunk_size, ff_use_sru, ff_sparsity,
                         attention_type):
  """Returns a list of layers implementing a Transformer encoder-decoder block.

  The input is a triple (decoder_activations, mask, encoder_activiations) where
  the mask is created from the original input token IDs to prevent attending to
  the padding part of the encoder.

  Args:
    d_model: Final dimension of tensors at most points in the model, including
        the initial embedding output.
    d_ff: Size of special dense layer in the feed-forward part of each block.
    n_heads: Number of attention heads.
    dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout within a block.
    dropout_shared_axes: Tensor axes on which to share a dropout mask.
        Sharing along batch and sequence axes (`dropout_shared_axes=(0,1)`) is
        a useful way to save memory and apply consistent masks to activation
        vectors at different sequence positions.
    mode: If `'train'`, each block will include dropout; else, it will
        pass all values through unaltered.
    ff_activation: Type of activation function at the end of each block; must
        be an activation-type subclass of `Layer`.
    ff_dropout: Stochastic rate (probability) for dropping an activation value
        when applying dropout after the FF dense layer.
    ff_chunk_size: int; if > 0, chunk feed-forward into this-sized chunks
    ff_use_sru: int; if > 0, we use this many SRU layers instead of feed-forward
    ff_sparsity: int, if > 0 use sparse feed-forward block with this sparsity
    attention_type: The attention layer to use.

  Returns:
    A list of layers which maps triples (decoder_activations, mask,
    encoder_activations) to triples of the same sort.
  """
  def _Dropout():
    return tl.Dropout(rate=dropout, shared_axes=dropout_shared_axes, mode=mode)

  # TODO(afrozm): Should this layer be configurable too?
  # TODO(afrozm): Should this layer be configurable too?
  # TODO(afrozm): Should this layer be configurable too?
  attention_qkv = tl.AttentionQKV(
      d_model, n_heads=n_heads, dropout=dropout, mode=mode)

  # TODO(afrozm): Check if masked should be True
  # TODO(afrozm): Check if masked should be True
  # TODO(afrozm): Check if masked should be True
  causal_attention = reformer.ApplyAttentionLayer(
      attention_type,
      d_model,
      n_heads,
      d_model // n_heads,
      d_model // n_heads,
      causal=True,
      masked=True,
      attention_dropout=dropout,
      output_dropout=dropout,
      mode=mode)

  feed_forward = reformer.FeedForwardWithOptions(d_model, d_ff, dropout,
                                                 dropout_shared_axes,
                                                 ff_activation, ff_dropout,
                                                 ff_chunk_size, ff_use_sru,
                                                 ff_sparsity, mode)

  return [                             # vec_d masks vec_e
      tl.Residual(
          tl.LayerNorm(),              # vec_d ..... .....
          causal_attention,            # vec_d ..... .....
          _Dropout(),                  # vec_d ..... .....
      ),
      tl.Residual(
          tl.LayerNorm(),              # vec_d ..... .....
          tl.Select([0, 2, 2, 1, 2]),  # vec_d vec_e vec_e masks vec_e
          attention_qkv,               # vec_d masks vec_e
          _Dropout(),                  # vec_d masks vec_e
      ),
      tl.Residual(
          feed_forward                 # vec_d masks vec_e
      ),
  ]
