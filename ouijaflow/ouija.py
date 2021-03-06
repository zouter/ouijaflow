from .dropout_normal import DropoutNormal
from .logit_shift_bijector import LogitShiftBijector

from edward.models import Normal, Gamma, Beta, Categorical, Mixture, ParamMixture
import tensorflow as tf
import edward as ed
import pandas as pd


class ouija:

    def __init__(self):
        self.Q = 1
    
    def fit(self, Y, n_iter = 1000, logdir = None):
        """ Fit the Ouija model using variational inference with reparametrisation gradient

        Args:
            Y (numpy.array): A cell-by-gene matrix of gene expression values representing non-negative log expression
            n_iter (int): Number of iterations of optimisation to perform
            logdir (str): Directory for logging (debugging)
        """
        self.N = Y.shape[0] # Number of cells
        self.G = Y.shape[1] # Number of genes

        approx_dict,Y_param = self._build_model_and_approximations()

        data_dict = {Y_param: Y}

        inference = ed.KLqp(approx_dict, data = data_dict)
        inference.run(n_iter = n_iter, logdir = logdir)

        self.inference = inference # Save this for a rainy day

    
    def _build_model_and_approximations(self):
        """ Form likelihood and approximating distributions of Ouija

        """
        N = self.N
        G = self.G
        Q = self.Q

        ds = tf.contrib.distributions


        k = Normal(loc = tf.zeros([G,Q]), scale = 50 * tf.ones([G,Q]), name = "k")
        t0 = Normal(loc = 0.5 * tf.ones(G), scale = 1 * tf.ones(G))

        mu0 = Gamma(concentration = 2 * tf.ones(G), rate = tf.ones(G))

        z = Normal(loc = 0.5 * tf.ones([N,Q]), scale = tf.ones([N,Q]))

        phi = Gamma(concentration = 2 * tf.ones(1), rate = tf.ones(1))
        pbeta = Normal(loc = tf.zeros(2), scale = tf.ones(2))

        cell_mat = tf.stack([tf.reshape(z, [-1]), -tf.ones(N)], 1)
        gene_mat = tf.stack([tf.reshape(k, [-1]), tf.reshape(k, [-1]) * tf.reshape(t0, [-1])], 1)

        factor_mult = tf.matmul(cell_mat, gene_mat, transpose_b = True) 
        mu = mu0 * tf.nn.sigmoid(factor_mult)
        
        prob_dropout = pbeta[0] + pbeta[1] * mu

        Y = DropoutNormal(p_dropout = prob_dropout, loc = mu, scale = tf.sqrt(1 + phi * mu))
        Y._p_dropout = prob_dropout

        self.qk = Normal(loc = tf.Variable(tf.zeros([G, Q])),
           scale = tf.nn.softplus(tf.Variable(tf.zeros([G, Q]))))

        self.qz = ed.models.TransformedDistribution(
            distribution = ed.models.NormalWithSoftplusScale(loc = tf.Variable(tf.zeros([N,Q])),
                                                            scale = tf.Variable(tf.ones([N,Q]))),
            bijector = LogitShiftBijector(a = tf.zeros([N,Q]), b = tf.ones([N,Q])),
            name = "qz"
        )

        self.qmu0 = ed.models.TransformedDistribution(
            distribution = ed.models.NormalWithSoftplusScale(loc = tf.Variable(tf.zeros(G)),
                                                            scale = tf.Variable(tf.ones(G))),
            bijector = ds.bijectors.Exp(),
            name = "qmu0"
        )

        self.qphi = ed.models.TransformedDistribution(
            distribution = ed.models.NormalWithSoftplusScale(loc = tf.Variable(tf.zeros(1)),
                                                            scale = tf.Variable(tf.ones(1))),
            bijector = ds.bijectors.Exp(),
            name = "qphi"
        )

        self.qt0 = ed.models.TransformedDistribution(
            distribution = ed.models.NormalWithSoftplusScale(loc = tf.Variable(tf.zeros(G)),
                                                            scale = tf.Variable(tf.ones(G))),
            bijector = LogitShiftBijector(a = tf.zeros(G), b = tf.ones(G)),
            name = "qt0"
        )

        self.qbeta = Normal(loc = tf.Variable(tf.zeros(2)),
                scale = tf.nn.softplus(tf.Variable(tf.ones(2))))

        approx_dict = {
            k: self.qk,
            z: self.qz,
            mu0: self.qmu0,
            phi: self.qphi,
            t0: self.qt0,
            pbeta: self.qbeta
        }

        return approx_dict, Y

    def trajectory(self):
        """ Returns a 1-D numpy array holding the maximum a-posteriori (MAP) pseudotimes

        """
        return self.qz.bijector.forward(self.qz.distribution.parameters['loc']).eval().reshape(-1)

    def gene_behaviour(self):
        """ Returns a pd.DataFrame with the gene-specific parameters

        The data frame has the following columns:
        1) k_mean: The posterior mean of the activation strength parameters
        2) k_lower: The posterior mean minus one s.d. of the activation strength parameters
        3) k_upper: The posterior mean plus one s.d. of the activation strength parameters
        4) t0_mean: The posterior mean of the activation time parameters
        5) t0_lower: The posterior mean minus one s.d. of the activation time parameters
        6) t0_upper: The posterior mean plus one s.d. of the activation time parameters
        7) mu0_mean: The posterior mean of the half-peak expression parameter
        """

        t0_sd = tf.nn.softplus(self.qt0.distribution.parameters['scale'])
        k_sd = tf.nn.softplus(self.qk.parameters['scale'])

        k_mean = self.qk.parameters['loc']
        t0_mean = self.qt0.distribution.parameters['loc']

        mu0_mean = self.qmu0.bijector.forward(self.qmu0.distribution.parameters['loc'])

        gene_df = pd.DataFrame({
            "k_mean": k_mean.eval().reshape(-1),
            "k_lower": (k_mean - k_sd).eval().reshape(-1),
            "k_upper": (k_mean + k_sd).eval().reshape(-1),
            "t0_mean": self.qt0.bijector.forward(t0_mean).eval().reshape(-1),
            "t0_lower": self.qt0.bijector.forward(t0_mean - t0_sd).eval().reshape(-1),
            "t0_upper": self.qt0.bijector.forward(t0_mean + t0_sd).eval().reshape(-1),
            "mu0_mean": mu0_mean.eval().reshape(-1)
        })

        return gene_df

    def approx_dists(self):
        """ Get the dictionary of the approximating distributions """

        approx_dict = {
            "k": self.qk,
            "z": self.qz,
            "mu0": self.qmu0,
            "phi": self.qphi,
            "t0": self.qt0,
            "pbeta": self.qbeta
        }

        return approx_dict