# coding=utf-8
# Copyright 2018 The TF-Agents Authors.
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

"""Unit tests for PyUniformReplayBuffer and PyHashedReplayBuffer."""

from __future__ import division
from __future__ import unicode_literals

import os

from absl.testing import parameterized
import numpy as np
import tensorflow as tf

from tf_agents.environments import time_step as ts
from tf_agents.environments import trajectory
from tf_agents.policies import policy_step
from tf_agents.replay_buffers import py_hashed_replay_buffer
from tf_agents.replay_buffers import py_uniform_replay_buffer
from tf_agents.specs import array_spec
from tf_agents.utils import nest_utils


def next_dataset_element(test_case, dataset):
  """Utility function to iterate over tf.data.Datasets in both TF 1.x and 2.x.

  TensorFlow 1.x and 2.x have different mechanisms for iterating over elements
  of a tf.data.Dataset. TensorFlow 1.x would require something like:

  itr = tf.data.Dataset.range(10).make_one_shot_iterator()
  get_next = itr.get_next()
  with tf.Session() as sess:
    for _ in range(10):
      item = sess.run(get_next)
      process(item)

  While TensorFlow 2.x enables something simpler like:

  for item in tf.data.Dataset.range(10):
    process(item)

  That simpler latter form is also available in TensorFlow 1.x when running
  with eager execution enabled.

  This function accomodates for the differing styles using:

  next_element = next_dataset_element(self, tf.data.Dataset.range(10))
  for _ in range 10:
    process(next_element())

  Args:
    test_case: The tf.test.TestCase object of the test calling this function.
    dataset: A tf.data.Dataset object.

  Returns:
    A Python function that returns successive elements from dataset on each call
    (using test_case.evaluate() in TensorFlow 1.x).
  """
  if tf.executing_eagerly():
    itr = iter(dataset)
    return lambda: next(itr)
  get_next = tf.compat.v1.data.make_one_shot_iterator(dataset).get_next()
  return lambda: test_case.evaluate(get_next)


class FrameBufferTest(tf.test.TestCase):

  def testFrameBuffer(self):
    fb = py_hashed_replay_buffer.FrameBuffer()
    a = np.random.randint(low=0, high=256, size=[84, 84, 1], dtype=np.uint8)
    h = fb.add_frame(a)
    fb.on_delete([h])
    self.assertEqual(0, len(fb))

    a = np.random.randint(low=0, high=256, size=[84, 84, 1], dtype=np.uint8)
    b = np.random.randint(low=0, high=256, size=[84, 84, 1], dtype=np.uint8)
    fb.add_frame(a)
    h = fb.add_frame(b)
    fb.on_delete([h])
    self.assertEqual(1, len(fb))


class PyUniformReplayBufferTest(parameterized.TestCase, tf.test.TestCase):

  def _create_replay_buffer(self, rb_cls):
    self._stack_count = 4
    self._single_shape = (15, 15, 1)
    shape = (15, 15, self._stack_count)
    observation_spec = array_spec.ArraySpec(shape, np.int32, 'obs')
    time_step_spec = ts.time_step_spec(observation_spec)
    action_spec = policy_step.PolicyStep(array_spec.BoundedArraySpec(
        shape=(), dtype=np.int32, minimum=0, maximum=1, name='action'))
    self._trajectory_spec = trajectory.from_transition(
        time_step_spec, action_spec, time_step_spec)

    self._capacity = 32
    self._replay_buffer = rb_cls(
        data_spec=self._trajectory_spec, capacity=self._capacity)

  def _fill_replay_buffer(self):
    # Generate N frames: the value of pixels is the frame index.
    # The observations will be generated by stacking K frames out of those N,
    # generating some redundancies between the observations.
    single_frames = []
    frame_count = 100
    for k in range(frame_count):
      single_frames.append(np.full(self._single_shape, k, dtype=np.int32))

    # Add stack of frames to the replay buffer.
    time_steps = []
    for k in range(len(single_frames) - self._stack_count + 1):
      observation = np.concatenate(single_frames[k:k + self._stack_count],
                                   axis=-1)
      time_steps.append(ts.transition(observation, reward=0.0))

    self._transition_count = len(time_steps) - 1
    dummy_action = policy_step.PolicyStep(np.int32(0))
    for k in range(self._transition_count):
      self._replay_buffer.add_batch(nest_utils.batch_nested_array(
          trajectory.from_transition(
              time_steps[k], dummy_action, time_steps[k + 1])))

  def _generate_replay_buffer(self, rb_cls):
    self._create_replay_buffer(rb_cls)
    self._fill_replay_buffer()

  @parameterized.named_parameters(
      [('WithoutHashing', py_uniform_replay_buffer.PyUniformReplayBuffer),
       ('WithHashing', py_hashed_replay_buffer.PyHashedReplayBuffer)])
  def testEmptyBuffer(self, rb_cls):
    self._create_replay_buffer(rb_cls=rb_cls)
    ds = self._replay_buffer.as_dataset()
    if tf.executing_eagerly():
      next(iter(ds))
    else:
      get_next = tf.compat.v1.data.make_one_shot_iterator(ds).get_next()
      self.evaluate(get_next)

  @parameterized.named_parameters(
      [('WithoutHashing', py_uniform_replay_buffer.PyUniformReplayBuffer),
       ('WithHashing', py_hashed_replay_buffer.PyHashedReplayBuffer)])
  def testEmptyBufferBatchSize(self, rb_cls):
    self._create_replay_buffer(rb_cls=rb_cls)
    ds = self._replay_buffer.as_dataset(sample_batch_size=2)
    if tf.executing_eagerly():
      next(iter(ds))
    else:
      get_next = tf.compat.v1.data.make_one_shot_iterator(ds).get_next()
      self.evaluate(get_next)

  @parameterized.named_parameters(
      [('WithoutHashing', py_uniform_replay_buffer.PyUniformReplayBuffer),
       ('WithHashing', py_hashed_replay_buffer.PyHashedReplayBuffer)])
  def testEmptyBufferNumSteps(self, rb_cls):
    self._create_replay_buffer(rb_cls=rb_cls)
    ds = self._replay_buffer.as_dataset(num_steps=2)
    if tf.executing_eagerly():
      next(iter(ds))
    else:
      get_next = tf.compat.v1.data.make_one_shot_iterator(ds).get_next()
      self.evaluate(get_next)

  @parameterized.named_parameters(
      [('WithoutHashing', py_uniform_replay_buffer.PyUniformReplayBuffer),
       ('WithHashing', py_hashed_replay_buffer.PyHashedReplayBuffer)])
  def testReplayBufferCircular(self, rb_cls):
    self._generate_replay_buffer(rb_cls=rb_cls)

    # Since data is added in a circular way, we know that frames sampled from
    # the replay buffer should not have values below a given threshold.
    ds = self._replay_buffer.as_dataset()
    next_trajectory = next_dataset_element(self, ds)
    min_value = self._transition_count - self._capacity
    for _ in range(200):
      traj = next_trajectory()
      self.assertLessEqual(min_value, traj.observation[0, 0, 0])
      self.assertAllEqual(traj.observation[:, :, 0] + 1,
                          traj.observation[:, :, 1])
      self.assertAllEqual(traj.observation[:, :, 0] + 2,
                          traj.observation[:, :, 2])
      self.assertAllEqual(traj.observation[:, :, 0] + 3,
                          traj.observation[:, :, 3])

  def testSampleDoesNotCrossHead(self):
    np.random.seed(12345)

    data_spec = array_spec.ArraySpec((), np.int32)
    replay_buffer = py_uniform_replay_buffer.PyUniformReplayBuffer(
        data_spec=data_spec, capacity=10)

    # Seed RB with 5 elements to move head to position 5.
    for _ in range(5):
      replay_buffer.add_batch(np.array([0]))

    # Fill RB with elements 0-9.
    for i in range(10):
      replay_buffer.add_batch(np.array([i]))

    # Sample with num_steps = 2. We should never sample (9, 0) since this is an
    # invalid transition. With 1000 samples, the probability of sampling (9, 0)
    # if it were not protected against would be (1 - (9/10)^10000) ~= 1.
    sample_frequency = [0 for _ in range(10)]
    for _ in range(10000):
      (first, second) = replay_buffer.get_next(num_steps=2, time_stacked=False)
      self.assertNotEqual(np.array(9), first)
      self.assertNotEqual(np.array(0), second)
      sample_frequency[first] += 1

    # 0-9 should all have been sampled about 10000/9 ~= 1111. We allow a delta
    # of 150 off of 1111 -- the chance each sample frequency is within this
    # range is 99.9998% (computed using the pmf of the binomial distribution).
    # And since we fix the random seed, this test is repeatable.
    for i in range(9):
      self.assertAlmostEqual(10000 / 9, sample_frequency[i], delta=150)

  @parameterized.named_parameters(
      [('WithoutHashing', py_uniform_replay_buffer.PyUniformReplayBuffer),
       ('WithHashing', py_hashed_replay_buffer.PyHashedReplayBuffer)])
  def testSampleBatches(self, rb_cls):
    self._generate_replay_buffer(rb_cls=rb_cls)

    ds = self._replay_buffer.as_dataset(sample_batch_size=5)
    next_trajectory = next_dataset_element(self, ds)
    self.assertEqual(list(ds.output_shapes.observation), [5, 15, 15, 4])
    self.assertEqual(list(ds.output_shapes.action), [5])
    traj = next_trajectory()
    self.assertEqual(traj.observation.shape, (5, 15, 15, 4))
    self.assertEqual(traj.step_type.shape, (5,))

  @parameterized.named_parameters(
      [('WithoutHashing', py_uniform_replay_buffer.PyUniformReplayBuffer),
       ('WithHashing', py_hashed_replay_buffer.PyHashedReplayBuffer)])
  def testSampleBatchesWithNumSteps(self, rb_cls):
    self._generate_replay_buffer(rb_cls=rb_cls)

    ds = self._replay_buffer.as_dataset(sample_batch_size=5, num_steps=3)
    self.assertEqual(list(ds.output_shapes.observation), [5, 3, 15, 15, 4])
    self.assertEqual(list(ds.output_shapes.action), [5, 3])
    next_trajectory = next_dataset_element(self, ds)

    traj = next_trajectory()
    self.assertEqual(traj.observation.shape, (5, 3, 15, 15, 4))
    self.assertEqual(traj.action.shape, (5, 3))

  @parameterized.named_parameters(
      [('WithoutHashing', py_uniform_replay_buffer.PyUniformReplayBuffer),
       ('WithHashing', py_hashed_replay_buffer.PyHashedReplayBuffer)])
  def testNumStepsNoBatching(self, rb_cls):
    self._generate_replay_buffer(rb_cls=rb_cls)

    ds = self._replay_buffer.as_dataset(num_steps=3)
    self.assertEqual(list(ds.output_shapes.observation), [3, 15, 15, 4])
    self.assertEqual(list(ds.output_shapes.action), [3])
    next_trajectory = next_dataset_element(self, ds)

    traj = next_trajectory()
    self.assertEqual(traj.observation.shape, (3, 15, 15, 4))
    self.assertEqual(traj.action.shape, (3,))

  @parameterized.named_parameters(
      [('WithoutHashing', py_uniform_replay_buffer.PyUniformReplayBuffer),
       ('WithHashing', py_hashed_replay_buffer.PyHashedReplayBuffer)])
  def testCheckpointable(self, rb_cls):
    self._generate_replay_buffer(rb_cls=rb_cls)
    self.assertEqual(32, self._replay_buffer.size)

    with self.cached_session():
      directory = self.get_temp_dir()
      prefix = os.path.join(directory, 'ckpt')
      saver = tf.train.Checkpoint(rb=self._replay_buffer)
      save_path = saver.save(prefix)

      loaded_rb = (
          rb_cls(data_spec=self._trajectory_spec, capacity=self._capacity))
      loader = tf.train.Checkpoint(rb=loaded_rb)
      loader.restore(save_path).initialize_or_restore()
      self.assertEqual(32, loaded_rb.size)

      # Check that replay buffer contains the same items as before
      ds = loaded_rb.as_dataset()
      next_trajectory = next_dataset_element(self, ds)
      min_value = self._transition_count - self._capacity
      for _ in range(200):
        traj = next_trajectory()
        self.assertLessEqual(min_value, traj.observation[0, 0, 0])
        self.assertAllEqual(traj.observation[:, :, 0] + 1,
                            traj.observation[:, :, 1])
        self.assertAllEqual(traj.observation[:, :, 0] + 2,
                            traj.observation[:, :, 2])
        self.assertAllEqual(traj.observation[:, :, 0] + 3,
                            traj.observation[:, :, 3])


if __name__ == '__main__':
  tf.test.main()
