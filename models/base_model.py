import os
import torch
import util.util as util
from torch.autograd import Variable
from . import networks
import numpy as np


class BaseModel():
    def name(self):
        return 'BaseModel'

    def initialize(self, opt):
        self.opt = opt
        self.gpu_ids = opt.gpu_ids
        self.isTrain = opt.isTrain
        torch.cuda.set_device(self.gpu_ids[0])
        self.Tensor = torch.cuda.FloatTensor if self.gpu_ids else torch.Tensor       
        self.save_dir = os.path.join(opt.checkpoints_dir, opt.name)

    def init_data(self, opt, use_D=True, use_D2=True, use_E=True, use_vae=True):
        print('---------- Networks initialized -------------')
        # load/define networks: define G
        if self.opt.which_image_encode == 'groundTruth':
            self.netG = networks.define_G(opt.input_nc, opt.output_nc, opt.nz, opt.ngf,
                                        which_model_netG=opt.which_model_netG,
                                        norm=opt.norm, nl=opt.nl, use_dropout=opt.use_dropout, init_type=opt.init_type,
                                        gpu_ids=self.gpu_ids, where_add=self.opt.where_add, upsample=opt.upsample)
        elif self.opt.which_image_encode == 'contour':
            self.netG = networks.define_G(3, opt.output_nc, opt.nz, opt.ngf,
                                        which_model_netG=opt.which_model_netG,
                                        norm=opt.norm, nl=opt.nl, use_dropout=opt.use_dropout, init_type=opt.init_type,
                                        gpu_ids=self.gpu_ids, where_add=self.opt.where_add, upsample=opt.upsample)
        networks.print_network(self.netG)
        self.netD, self.netD2, self.netDp = None, None, None
        self.netE, self.netDZ = None, None

        # if opt.isTrain:
        use_sigmoid = opt.gan_mode == 'dcgan'

        D_output_nc = opt.input_nc + opt.output_nc if self.opt.conditional_D else opt.output_nc
        # define D
        if not opt.isTrain:
            use_D = False
            use_D2 = False

        if use_D:
            self.netD = networks.define_D(D_output_nc, opt.ndf,
                                          which_model_netD=opt.which_model_netD,
                                          norm=opt.norm, nl=opt.nl,
                                          use_sigmoid=use_sigmoid, init_type=opt.init_type, num_Ds=opt.num_Ds, gpu_ids=self.gpu_ids)
            networks.print_network(self.netD)
        if use_D2:
            self.netD2 = networks.define_D(D_output_nc, opt.ndf,
                                           which_model_netD=opt.which_model_netD2,
                                           norm=opt.norm, nl=opt.nl,
                                           use_sigmoid=use_sigmoid, init_type=opt.init_type, num_Ds=opt.num_Ds, gpu_ids=self.gpu_ids)
            networks.print_network(self.netD2)

        # define E
        if use_E:
            if self.opt.which_image_encode == 'groundTruth':
                self.netE = networks.define_E(opt.output_nc, opt.nz, opt.nef,
                                            which_model_netE=opt.which_model_netE,
                                            norm=opt.norm, nl=opt.nl,
                                            init_type=opt.init_type, gpu_ids=self.gpu_ids,
                                            vaeLike=use_vae)
            elif self.opt.which_image_encode == 'contour':
                self.netE = networks.define_E(input_nc=1, output_nc=opt.nz, ndf=opt.nef,
                                              which_model_netE=opt.which_model_netE,
                                              norm=opt.norm, nl=opt.nl,
                                              init_type=opt.init_type, gpu_ids=self.gpu_ids,
                                              vaeLike=use_vae)
            #print self.netE(Variable(torch.rand(3,3,256,256)).cuda())
            networks.print_network(self.netE)

        if not opt.isTrain:
            self.load_network_test(self.netG, opt.G_path)

            if use_E:
                self.load_network_test(self.netE, opt.E_path)

        if opt.isTrain and opt.continue_train:
            self.load_network(self.netG, 'G', opt.which_epoch)

            if use_D:
                self.load_network(self.netD, 'D', opt.which_epoch)
            if use_D2:
                self.load_network(self.netD, 'D2', opt.which_epoch)

            if use_E:
                self.load_network(self.netE, 'E', opt.which_epoch)
        print('-----------------------------------------------')

        # define loss functions
        self.criterionGAN = networks.GANLoss(
            mse_loss=not use_sigmoid, tensor=self.Tensor)
	self.wGANloss = networks.wGANLoss(tensor=self.Tensor)
        self.criterionL1 = torch.nn.L1Loss()
        self.criterionZ = torch.nn.L1Loss()

        if opt.isTrain:
            # initialize optimizers
            self.schedulers = []
            self.optimizers = []
            self.optimizer_G = torch.optim.Adam(
                self.netG.parameters(), lr=opt.lr, betas=(opt.beta1, 0.999))
            self.optimizers.append(self.optimizer_G)
            if use_E:
                if opt.which_optimizer == 'Adam':
                    self.optimizer_E = torch.optim.Adam(
                        self.netE.parameters(), lr=opt.lr, betas=(opt.beta1, 0.999))
                elif opt.which_optimizer == 'RMSprop':
                    self.optimizer_E = torch.optim.RMSprop(
                        self.netE.parameters(),lr=opt.lr)
                self.optimizers.append(self.optimizer_E)
            if use_D:
                if opt.which_optimizer =='Adam':
                    self.optimizer_D = torch.optim.Adam(self.netD.parameters(),
                                                        lr=opt.lr, betas=(opt.beta1, 0.999))
                elif opt.which_optimizer == 'RMSprop':
                    self.optimizer_D = torch.optim.RMSprop(self.netD.parameters(),lr=opt.lr)
                self.optimizers.append(self.optimizer_D)
            if use_D2:
                if opt.which_optimizer =='Adam':
                    self.optimizer_D2 = torch.optim.Adam(self.netD2.parameters(),
                                                         lr=opt.lr, betas=(opt.beta1, 0.999))
                elif opt.which_optimizer =='RMSprop':
                    self.optimizer_D2 = torch.optim.RMSprop(self.netD2.parameters(),lr=opt.lr)
                self.optimizers.append(self.optimizer_D2)

            for optimizer in self.optimizers:
                self.schedulers.append(networks.get_scheduler(optimizer, opt))
            # st()

        self.metric = 0

    def is_skip(self):
        return False

    def forward(self):
        pass

    def eval(self):
        pass

    def set_requires_grad(self, net, requires_grad=False):
        if net is not None:
            for param in net.parameters():
                param.requires_grad = requires_grad  # to avoid computation

    def balance(self):
        pass

    def update_D(self, data):
        pass

    def update_G(self):
        pass

    def get_current_visuals(self):
        return self.input

    def get_current_errors(self):
        return {}

    def save(self, label):
        pass

    # helper saving function that can be used by subclasses
    def save_network(self, network, network_label, epoch_label, gpu_ids):
        save_filename = '%s_net_%s.pth' % (epoch_label, network_label)
        save_path = os.path.join(self.save_dir, save_filename)
        torch.save(network.cpu().state_dict(), save_path)
        if len(gpu_ids) and torch.cuda.is_available():
            network.cuda(gpu_ids[0])

    # helper loading function that can be used by subclasses
    def load_network(self, network, network_label, epoch_label):
        save_filename = '%s_net_%s.pth' % (epoch_label, network_label)
        save_path = os.path.join(self.save_dir, save_filename)
        network.load_state_dict(torch.load(save_path))

    def load_network_test(self, network, network_path):
        network.load_state_dict(torch.load(network_path))

    def update_learning_rate(self):
        loss = self.get_measurement()
        for scheduler in self.schedulers:
            scheduler.step(loss)
        lr = self.optimizers[0].param_groups[0]['lr']
        print('learning rate = %.7f' % lr)

    def get_measurement(self):
        return None

    def get_z_random(self, batchSize, nz, random_type='gauss'):
        z = self.Tensor(batchSize, nz)
        if random_type == 'uni':
            z.copy_(torch.rand(batchSize, nz) * 2.0 - 1.0)
        elif random_type == 'gauss':
            z.copy_(torch.randn(batchSize, nz))
        z = Variable(z)
        return z

    # testing models
    def set_input(self, input):
        # get direciton
        AtoB = self.opt.which_direction == 'AtoB'
        # set input images
        input_A = input['A' if AtoB else 'B']
        input_B = input['B' if AtoB else 'A']
        if len(self.gpu_ids) > 0:
            input_A = input_A.cuda(self.gpu_ids[0], async=True)
            input_B = input_B.cuda(self.gpu_ids[0], async=True)
        self.input_A = input_A
        self.input_B = input_B
        # get image paths
        self.image_paths = input['A_paths' if AtoB else 'B_paths']

    def get_image_paths(self):
        return self.image_paths

    def test(self, z_sample):  # need to have input set already
        self.real_A = Variable(self.input_A, volatile=True)
        batchSize = self.input_A.size(0)
        z = self.Tensor(batchSize, self.opt.nz)
        z_torch = torch.from_numpy(z_sample)
        z.copy_(z_torch)
        # st()
        self.z = Variable(z, volatile=True)
        self.fake_B = self.netG.forward(self.real_A, self.z)
        self.real_B = Variable(self.input_B, volatile=True)

    def encode(self, input_data):
        return self.netE.forward(Variable(input_data, volatile=True))

    def encode_real_B(self):
        if self.opt.wether_encode_cloth:
            clip_start_index = (self.opt.fineSize-self.opt.encode_size)//2
            clip_end_index = clip_start_index + self.opt.encode_size
            clip_cloth = self.input_B[:,:,clip_start_index:clip_end_index,clip_start_index:clip_end_index ]
            self.z_encoded = self.encode(clip_cloth)
        else:
            self.z_encoded = self.encode(self.input_B)
        return util.tensor2vec(self.z_encoded)

    def real_data(self, input=None):
        if input is not None:
            self.set_input(input)
        return util.tensor2im(self.input_A), util.tensor2im(self.input_B)

    def test_simple(self, z_sample, input=None, encode_real_B=False):
        if input is not None:
            self.set_input(input)

        if encode_real_B:  # use encoded z
            z_sample = self.encode_real_B()

        self.test(z_sample)

        real_A = util.tensor2im(self.real_A.data)
        fake_B = util.tensor2im(self.fake_B.data)
        real_B = util.tensor2im(self.real_B.data)
        return self.image_paths, real_A, fake_B, real_B, z_sample
