import numpy as np
import tensorflow as tf
from keras.models import Model
from keras.applications.vgg16 import VGG16, preprocess_input
from keras.preprocessing import image
import keras.backend as K

from familyGan.stylegan_encoder.encoder.AdaBound import AdaBoundOptimizer


def load_images(images_list, img_size):
    loaded_images = list()
    for img_path in images_list:
        img = image.load_img(img_path, target_size=(img_size, img_size))
        img = np.expand_dims(img, 0)
        loaded_images.append(img)
    loaded_images = np.vstack(loaded_images)
    preprocessed_images = preprocess_input(loaded_images)
    return preprocessed_images


class PerceptualModel:
    def __init__(self, img_size, layer=9, batch_size=1, sess=None):
        self.sess = tf.get_default_session() if sess is None else sess
        K.set_session(self.sess)
        self.img_size = img_size
        self.layer = layer
        self.batch_size = batch_size

        self.perceptual_model = None
        self.ref_img_features = None
        self.features_weight = None
        self.loss = None

    def build_perceptual_model(self, generated_image_tensor):
        self.optimizer = tf.train.AdamOptimizer(learning_rate=0.05,
                                           beta1=0.5,
                                           beta2=0.5,
                                           epsilon=1e-8,)
        # self.optimizer = tf.train.GradientDescentOptimizer(learning_rate=0.1)

        # self.optimizer = AdaBoundOptimizer(learning_rate=0.1,
        #                                    final_lr=1,
        #                                    beta1=0.9,
        #                                    beta2=0.999, amsbound=False)

        vgg16 = VGG16(include_top=False, input_shape=(self.img_size, self.img_size, 3))
        self.perceptual_model = Model(vgg16.input, vgg16.layers[self.layer].output)
        generated_image = preprocess_input(tf.image.resize_images(generated_image_tensor,
                                                                  (self.img_size, self.img_size), method=1))
        generated_img_features = self.perceptual_model(generated_image)
        with tf.variable_scope("ref_img_features", reuse=tf.AUTO_REUSE) as scope:
            self.ref_img_features = tf.get_variable('ref_img_features', shape=generated_img_features.shape,
                                                    dtype='float32', initializer=tf.initializers.zeros())
        with tf.variable_scope("features_weight", reuse=tf.AUTO_REUSE) as scope:
            self.features_weight = tf.get_variable('features_weight', shape=generated_img_features.shape,
                                                   dtype='float32', initializer=tf.initializers.zeros())
        self.sess.run([self.features_weight.initializer, self.features_weight.initializer])

        self.loss = tf.losses.mean_squared_error(self.features_weight * self.ref_img_features,
                                                 self.features_weight * generated_img_features) / 82890.0

    def set_reference_images(self, images_list):
        assert (len(images_list) != 0 and len(images_list) <= self.batch_size)
        loaded_image = load_images(images_list, self.img_size)
        image_features = self.perceptual_model.predict_on_batch(loaded_image)

        # in case if number of images less than actual batch size
        # can be optimized further
        weight_mask = np.ones(self.features_weight.shape)
        if len(images_list) != self.batch_size:
            features_space = list(self.features_weight.shape[1:])
            existing_features_shape = [len(images_list)] + features_space
            empty_features_shape = [self.batch_size - len(images_list)] + features_space

            existing_examples = np.ones(shape=existing_features_shape)
            empty_examples = np.zeros(shape=empty_features_shape)
            weight_mask = np.vstack([existing_examples, empty_examples])

            image_features = np.vstack([image_features, np.zeros(empty_features_shape)])

        self.sess.run(tf.assign(self.features_weight, weight_mask))
        self.sess.run(tf.assign(self.ref_img_features, image_features))

    def set_reference_images_from_image(self, images_list):
        assert (len(images_list) != 0 and len(images_list) <= self.batch_size)
        loaded_image = preprocess_input(images_list)
        image_features = self.perceptual_model.predict_on_batch(loaded_image)

        # in case if number of images less than actual batch size
        # can be optimized further
        weight_mask = np.ones(self.features_weight.shape)
        if len(images_list) != self.batch_size:
            features_space = list(self.features_weight.shape[1:])
            existing_features_shape = [len(images_list)] + features_space
            empty_features_shape = [self.batch_size - len(images_list)] + features_space

            existing_examples = np.ones(shape=existing_features_shape)
            empty_examples = np.zeros(shape=empty_features_shape)
            weight_mask = np.vstack([existing_examples, empty_examples])

            image_features = np.vstack([image_features, np.zeros(empty_features_shape)])

        self.sess.run(tf.assign(self.features_weight, weight_mask))
        self.sess.run(tf.assign(self.ref_img_features, image_features))

    def optimize(self, vars_to_optimize, iterations=500, learning_rate=1.):
        vars_to_optimize = vars_to_optimize if isinstance(vars_to_optimize, list) else [vars_to_optimize]
        # self.optimizer._learning_rate = learning_rate  # for SGD optimizer
        # self.optimizer._lr = learning_rate  # for adam, etc
        # self.optimizer._final_lr = learning_rate * 0.3333333  # for adabound

        min_op = self.optimizer.minimize(self.loss, var_list=[vars_to_optimize])
        self.sess.run(tf.variables_initializer(self.optimizer.variables()))

        last_loss = None
        no_change_counter = 0
        delta = 0.1
        stop_count = 20
        for _ in range(iterations):
            _, loss = self.sess.run([min_op, self.loss])
            if last_loss is not None and abs(last_loss - loss) < delta:
                no_change_counter += 1
                if no_change_counter > stop_count and loss < 0.6:
                    print("early stopping")
                    break
            else:
                no_change_counter = 0
                last_loss = loss
            yield loss
